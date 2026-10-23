"""Exports a trained run to `traits-vN.tflite` + `traits-vN.json` and writes parity fixtures.

Order matters (CLAUDE.md, ML hygiene): quantize to INT8 first, compare it with the float model
per head on the test split, then fit the temperature and sorghum threshold on the INT8 outputs
of the validation split, because those are the outputs the phones will see.
"""

import datetime
import json
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf
from PIL import Image

from sorghum_model.calibration import (
    choose_sorghum_threshold,
    expected_calibration_error,
    fit_temperature,
    softmax,
)
from sorghum_model.manifest import ImageRecord, sha256_of_file
from sorghum_model.metadata import InputQuantization, build_metadata, model_file_names, write_metadata
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, ExportSettings
from sorghum_model.species_classes import SPECIES_CLASS_NAMES, SpeciesGroup, species_class
from sorghum_model.splits import Split, count_per_class_and_split
from sorghum_model.train import KERAS_MODEL_FILE, SAVED_MODEL_DIR, SHUFFLE_SEED, class_indices, load_images

FIXTURE_EXPECTATIONS_FILE = "expected.json"


def export_model(
    run_dir: Path,
    records: list[ImageRecord],
    splits: dict[str, Split],
    data_root: Path,
    version: int,
    output_dir: Path,
    fixtures_dir: Path,
    settings: ExportSettings,
    provenance: dict,
) -> Path:
    """Writes the model, its metadata and the fixtures; returns the metadata path."""
    train = [r for r in records if splits[r.sha256] is Split.TRAIN]
    validation = [r for r in records if splits[r.sha256] is Split.VALIDATION]
    test = [r for r in records if splits[r.sha256] is Split.TEST]

    representative = _sample(train, settings.representative_images)
    model_bytes = _convert_to_int8(run_dir / SAVED_MODEL_DIR, load_images(representative, data_root))
    runner = _TfliteRunner(model_bytes)

    validation_images = load_images(validation, data_root)
    validation_labels = class_indices(validation)
    test_images = load_images(test, data_root)
    test_labels = class_indices(test)

    float_model = keras.models.load_model(run_dir / KERAS_MODEL_FILE)
    float_test_logits = float_model.predict(test_images.astype(np.float32), verbose=0)
    int8_test_logits = runner.logits(test_images)
    int8_validation_logits = runner.logits(validation_images)

    temperature = fit_temperature(int8_validation_logits, validation_labels)
    sorghum_index = SPECIES_CLASS_NAMES.index(_sorghum_class_name())
    threshold = choose_sorghum_threshold(
        softmax(int8_validation_logits, temperature)[:, sorghum_index],
        validation_labels == sorghum_index,
        settings.sorghum_precision_target,
        settings.min_threshold_predictions,
    )

    model_file, metadata_file = model_file_names(version)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / model_file).write_bytes(model_bytes)

    metadata = build_metadata(
        version=version,
        created_on=datetime.date.today().isoformat(),
        input_size_px=MODEL_INPUT_SIZE_PX,
        input_quantization=runner.input_quantization,
        species_output_index=0,
        temperature=temperature,
        sorghum_threshold=threshold.threshold,
        evaluation=_evaluate(
            int8_test_logits, test_labels, temperature, threshold.threshold, sorghum_index, settings
        )
        | {
            "validationSorghumPrecision": threshold.precision,
            "validationSorghumRecall": threshold.recall,
        },
        quantization_parity=_quantization_parity(float_test_logits, int8_test_logits, test_labels),
        training_data=provenance
        | {
            "photosPerClassAndSplit": {
                f"{name}/{split.value}": count
                for (name, split), count in sorted(
                    count_per_class_and_split(records, splits).items(),
                    key=lambda item: (item[0][0], item[0][1].value),
                )
            },
            "modelFileSha256": sha256_of_file(output_dir / model_file),
        },
    )
    write_metadata(metadata, output_dir / metadata_file)
    _write_fixtures(test, test_images, runner, temperature, version, fixtures_dir, settings.fixture_images)
    return output_dir / metadata_file


class _TfliteRunner:
    """Runs the INT8 model the way the phones do: uint8 pixels in, float logits out."""

    def __init__(self, model_bytes: bytes) -> None:
        self._interpreter = tf.lite.Interpreter(model_content=model_bytes)
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        self._output = self._interpreter.get_output_details()[0]
        scale, zero_point = self._input["quantization"]
        self.input_quantization = InputQuantization(scale=float(scale), zero_point=int(zero_point))

    def logits(self, images: np.ndarray) -> np.ndarray:
        """Logits for (n, size, size, 3) uint8 images, one image at a time like on device."""
        rows = []
        for image in images:
            self._interpreter.set_tensor(self._input["index"], self._quantize(image)[np.newaxis])
            self._interpreter.invoke()
            rows.append(self._interpreter.get_tensor(self._output["index"])[0].copy())
        return np.stack(rows)

    def _quantize(self, image: np.ndarray) -> np.ndarray:
        # Same formula `shared/` applies from the metadata: q = v / scale + zeroPoint.
        quantization = self.input_quantization
        quantized = np.round(image.astype(np.float32) / quantization.scale + quantization.zero_point)
        return np.clip(quantized, 0, 255).astype(np.uint8)


def _convert_to_int8(saved_model_dir: Path, representative_images: np.ndarray) -> bytes:
    """Full-integer post-training quantization with uint8 input and float32 logits output."""

    def representative_dataset():
        for image in representative_images:
            yield [image[np.newaxis].astype(np.float32)]

    converter = tf.lite.TFLiteConverter.from_saved_model(str(saved_model_dir))
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = representative_dataset
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.uint8
    # Float logits keep temperature scaling and softmax exact in `shared/`.
    converter.inference_output_type = tf.float32
    return converter.convert()


def _quantization_parity(float_logits: np.ndarray, int8_logits: np.ndarray, labels: np.ndarray) -> dict:
    """Float vs INT8 on the test split, recorded in the metadata before shipping."""
    float_probabilities = softmax(float_logits)
    int8_probabilities = softmax(int8_logits)
    difference = np.abs(float_probabilities - int8_probabilities)
    return {
        "split": Split.TEST.value,
        "floatAccuracy": float((float_logits.argmax(axis=1) == labels).mean()),
        "int8Accuracy": float((int8_logits.argmax(axis=1) == labels).mean()),
        "top1Agreement": float((float_logits.argmax(axis=1) == int8_logits.argmax(axis=1)).mean()),
        "maxProbabilityDifference": float(difference.max()),
        "meanProbabilityDifference": float(difference.mean()),
    }


def _evaluate(logits, labels, temperature, threshold, sorghum_index, settings: ExportSettings) -> dict:
    """Held-out test numbers for the INT8 model, before and after temperature scaling."""
    calibrated = softmax(logits, temperature)
    passed = calibrated[:, sorghum_index] >= threshold
    is_sorghum = labels == sorghum_index
    per_class_accuracy = {}
    for index, name in enumerate(SPECIES_CLASS_NAMES):
        in_class = labels == index
        if in_class.any():
            per_class_accuracy[name] = float((calibrated[in_class].argmax(axis=1) == index).mean())
    return {
        "split": Split.TEST.value,
        "photos": int(len(labels)),
        "accuracy": float((calibrated.argmax(axis=1) == labels).mean()),
        "perClassAccuracy": per_class_accuracy,
        "eceBins": settings.ece_bins,
        "eceBeforeTemperature": expected_calibration_error(softmax(logits), labels, settings.ece_bins),
        "eceAfterTemperature": expected_calibration_error(calibrated, labels, settings.ece_bins),
        "testSorghumPrecision": float((passed & is_sorghum).sum() / max(passed.sum(), 1)),
        "testSorghumRecall": float((passed & is_sorghum).sum() / max(is_sorghum.sum(), 1)),
    }


def _write_fixtures(test, test_images, runner, temperature, version, fixtures_dir, count) -> None:
    """Writes model-input PNGs and the INT8 outputs both phone runtimes must reproduce (R7).

    Photos are taken round-robin over classes so every class is covered. They are stored at
    input size, so the parity test checks inference and not the resize.
    """
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    chosen = _round_robin_by_class(list(range(len(test))), test, count)
    logits = runner.logits(test_images[chosen])
    expectations = []
    for row, index in enumerate(chosen):
        record = test[index]
        file_name = f"species-{record.class_name}-{record.source}-{Path(record.source_id).stem}.png"
        Image.fromarray(test_images[index]).save(fixtures_dir / file_name)
        expectations.append(
            {
                "image": file_name,
                "classId": record.class_name,
                "logits": logits[row].tolist(),
                "probabilities": softmax(logits[row : row + 1], temperature)[0].tolist(),
                "license": record.license,
                "attribution": record.attribution,
            }
        )
    document = {"modelVersion": version, "head": "species", "fixtures": expectations}
    (fixtures_dir / FIXTURE_EXPECTATIONS_FILE).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


def _round_robin_by_class(indices: list[int], records: list[ImageRecord], count: int) -> list[int]:
    by_class: dict[str, list[int]] = {}
    for index in indices:
        by_class.setdefault(records[index].class_name, []).append(index)
    chosen: list[int] = []
    while len(chosen) < count and any(by_class.values()):
        for name in SPECIES_CLASS_NAMES:
            if by_class.get(name) and len(chosen) < count:
                chosen.append(by_class[name].pop(0))
    return chosen


def _sample(records: list[ImageRecord], count: int) -> list[ImageRecord]:
    order = np.random.default_rng(SHUFFLE_SEED).permutation(len(records))
    return [records[i] for i in order[:count]]


def _sorghum_class_name() -> str:
    names = [n for n in SPECIES_CLASS_NAMES if species_class(n).group is SpeciesGroup.SORGHUM]
    if len(names) != 1:
        raise ValueError(f"expected exactly one sorghum class, found {names}")
    return names[0]
