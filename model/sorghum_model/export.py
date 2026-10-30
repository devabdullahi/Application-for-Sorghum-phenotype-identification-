"""Exports a trained run to `traits-vN.tflite` + `traits-vN.json` and writes parity fixtures.

Order matters (CLAUDE.md, ML hygiene): quantize to INT8 first, compare it with the float model
per head on the test split, then fit the temperature and sorghum threshold on the INT8 outputs
of the validation split, because those are the outputs the phones will see.
"""

import datetime
import json
import tempfile
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf
from PIL import Image

from sorghum_model.calibration import (
    choose_sorghum_threshold,
    expected_calibration_error,
    fit_temperature,
    most_precise_sorghum_threshold,
    softmax,
)
from sorghum_model.manifest import ImageRecord, license_summary, sha256_of_file
from sorghum_model.metadata import InputQuantization, build_metadata, model_file_names, write_metadata
from sorghum_model.quantization import (
    LogitTolerance,
    logit_tolerance_fields,
    logit_quantization_step,
    measured_logit_tolerance,
    quantize_input,
)
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, Backbone, ExportSettings
from sorghum_model.ship_bar import (
    converter_version_problems,
    enforce_ship_bar,
    ship_bar_problems,
    sorghum_decision_accuracy,
)
from sorghum_model.species_classes import SPECIES_CLASS_NAMES, SpeciesGroup, species_class
from sorghum_model.splits import Split, count_per_class_and_split
from sorghum_model.train import (
    KERAS_MODEL_FILE,
    SHUFFLE_SEED,
    TRAINING_REPORT_FILE,
    class_indices,
    load_images,
)

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
    allow_below_bar: bool = False,
) -> Path:
    """Writes the model, its metadata and the fixtures; returns the metadata path.

    Raises BelowShipBarError, writing nothing, when the model misses ExportSettings' ship
    bar, unless `allow_below_bar` (diagnostic exports only; recorded as `belowBar`).
    """
    train = [r for r in records if splits[r.sha256] is Split.TRAIN]
    validation = [r for r in records if splits[r.sha256] is Split.VALIDATION]
    test = [r for r in records if splits[r.sha256] is Split.TEST]

    float_model = keras.models.load_model(run_dir / KERAS_MODEL_FILE)
    representative = _sample(train, settings.representative_images)
    model_bytes = convert_to_int8(float_model, load_images(representative, data_root))
    runner = TfliteRunner(model_bytes)

    validation_images = load_images(validation, data_root)
    validation_labels = class_indices(validation)
    test_images = load_images(test, data_root)
    test_labels = class_indices(test)

    float_test_logits = float_model.predict(test_images.astype(np.float32), verbose=0)
    float_validation_logits = float_model.predict(validation_images.astype(np.float32), verbose=0)
    int8_test_logits = runner.logits(test_images)
    int8_validation_logits = runner.logits(validation_images)

    temperature = fit_temperature(int8_validation_logits, validation_labels)
    sorghum_index = SPECIES_CLASS_NAMES.index(_sorghum_class_name())
    validation_sorghum = softmax(int8_validation_logits, temperature)[:, sorghum_index]
    is_validation_sorghum = validation_labels == sorghum_index
    threshold_problems = []
    try:
        threshold = choose_sorghum_threshold(
            validation_sorghum,
            is_validation_sorghum,
            settings.min_sorghum_precision,
            settings.min_threshold_predictions,
        )
    except ValueError as error:
        # Missing the precision floor is a ship-bar miss like the others: refused below
        # unless --allow-below-bar, which then uses the strictest threshold the data allows.
        threshold_problems.append(str(error))
        threshold = most_precise_sorghum_threshold(
            validation_sorghum, is_validation_sorghum, settings.min_threshold_predictions
        )

    evaluation = _evaluate(
        int8_test_logits, test_labels, temperature, threshold.threshold, sorghum_index, settings
    ) | {
        "validationSorghumPrecision": threshold.precision,
        "validationSorghumRecall": threshold.recall,
        "validationSorghumDecisionAccuracy": threshold.decision_accuracy,
    }
    parity = _quantization_parity(float_test_logits, int8_test_logits, test_labels)
    # For comparison only: what the float model would score with its own temperature and
    # threshold. The phones run the INT8 model, so the bar is judged on INT8.
    evaluation["float"] = _float_evaluation(
        float_validation_logits, validation_labels, float_test_logits, test_labels,
        sorghum_index, settings,
    )
    xnnpack_error = xnnpack_load_error(model_bytes)
    parity["loadsWithXnnpack"] = xnnpack_error is None
    parity["converterTensorflowVersion"] = tf.__version__
    # Checked before anything is written, so a model below the bar never reaches out_dir.
    # Phones run LiteRT with XNNPACK, so a model that loads only with the reference kernels
    # would fail on device.
    xnnpack_problems = [f"INT8 model does not load under XNNPACK: {xnnpack_error}"] if xnnpack_error else []
    problems = (
        threshold_problems
        + xnnpack_problems
        + converter_version_problems(tf.__version__, settings)
        + ship_bar_problems(
            evaluation["testSorghumDecisionAccuracy"],
            parity["floatAccuracy"],
            parity["int8Accuracy"],
            settings,
        )
    )
    below_bar = enforce_ship_bar(problems, allow_below_bar)

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
        evaluation=evaluation,
        quantization_parity=parity,
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
        }
        # Additive keys only: `shared/` does not read trainingData. "licenses" and
        # "nonCommercial" tell a reader whether the model may be used commercially.
        | license_summary(records),
        ship_bar={
            "minSorghumDecisionAccuracy": settings.min_sorghum_accuracy,
            "maxQuantizationAccuracyDelta": settings.max_quantization_accuracy_delta,
            "problems": problems,
        },
        below_bar=below_bar,
        backbone=_trained_backbone(run_dir),
    )
    write_metadata(metadata, output_dir / metadata_file)
    logit_tolerance = runner.logit_step() or measured_logit_tolerance(
        float_test_logits, int8_test_logits
    )
    _write_fixtures(
        test, test_images, runner, temperature, version, fixtures_dir, settings.fixture_images,
        logit_tolerance,
    )
    return output_dir / metadata_file


def xnnpack_load_error(model_bytes: bytes) -> str | None:
    """Loads the model with TFLite's default delegates (XNNPACK on CPU), as phones do.

    Returns None when it loads and runs one inference, else the interpreter's error.
    """
    try:
        interpreter = tf.lite.Interpreter(model_content=model_bytes)
        interpreter.allocate_tensors()
        detail = interpreter.get_input_details()[0]
        interpreter.set_tensor(detail["index"], np.zeros(detail["shape"], dtype=detail["dtype"]))
        interpreter.invoke()
    except (RuntimeError, ValueError) as error:
        return " ".join(str(error).split())
    return None


def _float_evaluation(validation_logits, validation_labels, test_logits, test_labels, sorghum_index, settings):
    """Test numbers of the float model with a temperature and threshold fitted on its own
    validation outputs, to show what quantization costs."""
    temperature = fit_temperature(validation_logits, validation_labels)
    validation_sorghum = softmax(validation_logits, temperature)[:, sorghum_index]
    is_sorghum = validation_labels == sorghum_index
    try:
        threshold = choose_sorghum_threshold(
            validation_sorghum, is_sorghum, settings.min_sorghum_precision, settings.min_threshold_predictions
        )
    except ValueError:
        threshold = most_precise_sorghum_threshold(validation_sorghum, is_sorghum, settings.min_threshold_predictions)
    evaluation = _evaluate(test_logits, test_labels, temperature, threshold.threshold, sorghum_index, settings)
    return evaluation | {
        "temperature": temperature,
        "sorghumThreshold": threshold.threshold,
        "validationSorghumPrecision": threshold.precision,
        "validationSorghumRecall": threshold.recall,
        "validationSorghumDecisionAccuracy": threshold.decision_accuracy,
    }


def _trained_backbone(run_dir: Path) -> str:
    """The backbone the run was trained with; runs from before the setting used the full variant."""
    report_path = run_dir / TRAINING_REPORT_FILE
    if report_path.exists():
        settings = json.loads(report_path.read_text(encoding="utf-8")).get("settings", {})
        if "backbone" in settings:
            return str(Backbone(settings["backbone"]))
    return str(Backbone.MOBILENET_V3_SMALL)


class TfliteRunner:
    """Runs the INT8 model the way the phones do: uint8 pixels in, float logits out."""

    def __init__(self, model_bytes: bytes) -> None:
        # The reference kernels, without the XNNPACK delegate: on TF 2.20 XNNPACK fails to
        # prepare this full-integer MobileNetV3 ("Node number 118 ... failed to prepare"), and
        # the expected outputs must not depend on a delegate's numerics anyway.
        self._interpreter = tf.lite.Interpreter(
            model_content=model_bytes,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
        )
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

    def logits_of_every_output(self, images: np.ndarray) -> list[np.ndarray]:
        """For a multi-head model: per output index (as the phones address heads), the logits
        of (n, size, size, 3) uint8 images, one image at a time like on device."""
        outputs = self._interpreter.get_output_details()
        rows: list[list[np.ndarray]] = [[] for _ in outputs]
        for image in images:
            self._interpreter.set_tensor(self._input["index"], self._quantize(image)[np.newaxis])
            self._interpreter.invoke()
            for index, output in enumerate(outputs):
                rows[index].append(self._interpreter.get_tensor(output["index"])[0].copy())
        return [np.stack(output_rows) for output_rows in rows]

    def _quantize(self, image: np.ndarray) -> np.ndarray:
        # Same formula and rounding `shared/` applies from the metadata (see quantize_input).
        return quantize_input(image, self.input_quantization.scale, self.input_quantization.zero_point)

    def logit_step(self) -> LogitTolerance | None:
        """The quantization step of the species logits, read from the model's tensors."""
        return logit_quantization_step(
            self._output,
            self._interpreter.get_tensor_details(),
            self._interpreter._get_ops_details(),  # no public API lists the ops
        )


def convert_to_int8(model: keras.Model, representative_images: np.ndarray) -> bytes:
    """Full-integer post-training quantization with uint8 input and float32 logits output.

    The SavedModel is written here, by the TensorFlow that converts it, and not by training:
    training runs on a newer TensorFlow than the phones' converter (ExportSettings.
    converter_tensorflow_version), and a graph from one version is not guaranteed to convert
    the same way in another.
    """

    def representative_dataset():
        for image in representative_images:
            yield [image[np.newaxis].astype(np.float32)]

    with tempfile.TemporaryDirectory() as directory:
        saved_model_dir = Path(directory) / "saved_model"
        model.export(str(saved_model_dir))
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
    predicted = calibrated.argmax(axis=1)
    per_class_accuracy = {}
    per_class_precision = {}
    for index, name in enumerate(SPECIES_CLASS_NAMES):
        in_class = labels == index
        if in_class.any():
            # Recall: share of this class's photos named correctly.
            per_class_accuracy[name] = float((predicted[in_class] == index).mean())
        predicted_as_class = predicted == index
        if predicted_as_class.any():
            per_class_precision[name] = float((labels[predicted_as_class] == index).mean())
    return {
        "split": Split.TEST.value,
        "photos": int(len(labels)),
        "accuracy": float((calibrated.argmax(axis=1) == labels).mean()),
        "perClassAccuracy": per_class_accuracy,
        "perClassRecall": per_class_accuracy,
        "perClassPrecision": per_class_precision,
        "eceBins": settings.ece_bins,
        "eceBeforeTemperature": expected_calibration_error(softmax(logits), labels, settings.ece_bins),
        "eceAfterTemperature": expected_calibration_error(calibrated, labels, settings.ece_bins),
        "testSorghumDecisionAccuracy": sorghum_decision_accuracy(
            calibrated[:, sorghum_index], is_sorghum, threshold
        ),
        "testSorghumPrecision": float((passed & is_sorghum).sum() / max(passed.sum(), 1)),
        "testSorghumRecall": float((passed & is_sorghum).sum() / max(is_sorghum.sum(), 1)),
    }


def _write_fixtures(
    test, test_images, runner, temperature, version, fixtures_dir, count, logit_tolerance
) -> None:
    """Writes model-input PNGs and the INT8 outputs both phone runtimes must reproduce (R7).

    Photos are taken round-robin over classes so every class is covered. They are stored at
    input size, so the parity test checks inference and not the resize. The top-level
    `logitStep` (or, without an int8 logit tensor, `logitParityMaxDelta`) tells the parity
    tests how far a phone's logits may differ from these. `logitStep` is always written (the
    measured delta when there is no step); `logitToleranceSource` says which it is.
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
    document = {
        "modelVersion": version,
        "head": "species",
        **logit_tolerance_fields(logit_tolerance),
        "fixtures": expectations,
    }
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
