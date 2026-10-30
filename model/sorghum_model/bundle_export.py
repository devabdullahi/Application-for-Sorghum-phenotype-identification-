"""Builds traits-vN from two finished exports: the species model and the basic-race output (#45).

Inputs are the shipped species export (`traits-v2.{tflite,json}` and its parity fixtures) and
the basic-race export (`basic-race-v1.{tflite,json}`, #37). Neither model is retrained or
re-quantized. `model_bundle.merge_models` packs both into one file (ADR-0012). Output 0 is
species and output 1 is basicRace. This module then:

1. checks each source file against the sha256 its own metadata recorded;
2. checks the merged outputs are bit-identical to each source on every given photo, so the
   evaluations recorded for both models still describe the merged file;
3. writes `traits-vN.json`: the species head unchanged, plus a `basicRace` head carrying its
   answer rule, the locked evaluation (#44) and `experimental: true`;
4. writes parity fixtures for both heads. The species fixtures are the source export's own
   images, re-recorded for version N. The basic-race fixtures are test photos with the logits,
   probabilities and answer (group or "unrecognized") computed here.

Needs the `export` extra (TensorFlow 2.17), like every step that writes a phone model.
"""

import copy
import datetime
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tensorflow as tf
from PIL import Image

from sorghum_model.calibration import softmax
from sorghum_model.cultivar_manifest import CultivarImageRecord
from sorghum_model.manifest import sha256_of_file
from sorghum_model.metadata import (
    BASIC_RACE_HEAD_ID,
    SPECIES_HEAD_ID,
    basic_race_head,
    model_file_names,
    write_metadata,
)
from sorghum_model.model_bundle import merge_models, verify_merged_outputs
from sorghum_model.preprocessing import load_model_input
from sorghum_model.quantization import logit_quantization_step, logit_tolerance_fields, quantize_input
from sorghum_model.race_evaluation import GATE_COVERAGE, returned_group
from sorghum_model.race_photos import RacePhoto
from sorghum_model.settings import RaceEvaluationSettings

FIXTURE_EXPECTATIONS_FILE = "expected.json"
SPECIES_OUTPUT_INDEX = 0
BASIC_RACE_OUTPUT_INDEX = 1
# Prefix of the basic-race network's tensor names inside the merged file.
BASIC_RACE_TENSOR_PREFIX = "basic_race/"

# Shown to anyone who reads the metadata. Its numbers are basic-race-v1's locked test results (#44).
BASIC_RACE_STATUS = (
    "EXPERIMENTAL. Does not meet the 89% race accuracy goal (ADR-0011, defined over the fifteen "
    "races). The gate rule scored 0.965 selective accuracy at 0.793 test coverage, so it misses "
    "the 0.80 coverage floor. Kafir, Bicolor and Guinea are mostly unrecognized. This is a hint "
    "over five basic races only. It is never a cultivar result and never gates anything."
)


@dataclass(frozen=True)
class SourceExport:
    """One finished export: the model file and the metadata written next to it."""

    model_path: Path
    metadata: dict

    @property
    def model_bytes(self) -> bytes:
        return self.model_path.read_bytes()


def read_source_export(model_path: Path, metadata_path: Path, recorded_sha256: str) -> SourceExport:
    """Reads an export, refusing a model file that is not the one its metadata describes."""
    actual = sha256_of_file(model_path)
    if actual != recorded_sha256:
        raise ValueError(f"{model_path.name} has sha256 {actual}, but its metadata records {recorded_sha256}")
    return SourceExport(model_path, json.loads(metadata_path.read_text(encoding="utf-8")))


def bundle_species_and_basic_race(
    *,
    species: SourceExport,
    species_fixtures_dir: Path,
    basic_race: SourceExport,
    race_test_photos: Sequence[RacePhoto],
    race_verification_photos: Sequence[RacePhoto],
    image_records: dict[str, CultivarImageRecord],
    data_root: Path,
    version: int,
    out_dir: Path,
    fixtures_root: Path,
    race_fixture_count_per_race: int,
) -> dict:
    """Writes `traits-v<version>.{tflite,json}` and both fixture sets; returns the metadata.

    `race_verification_photos` are the photos the bit-identity check runs on, besides the
    species fixtures. `race_test_photos` are the basic-race test photos the fixtures are taken
    from. `image_records` maps an image path to its manifest record, for licence and
    attribution. Fixtures go to `fixtures_root/species` and `fixtures_root/basic-race`.
    """
    species_head = species.metadata["heads"][SPECIES_HEAD_ID]
    if species_head["outputIndex"] != SPECIES_OUTPUT_INDEX:
        raise ValueError(f"species export reads output {species_head['outputIndex']}; the bundle needs it first")
    input_spec = species.metadata["input"]
    race_input = basic_race.metadata["input"]
    if race_input["sizePx"] != input_spec["widthPx"] or race_input["sizePx"] != input_spec["heightPx"]:
        raise ValueError("the two exports were made for different input sizes")
    scale, zero_point = input_spec["quantization"]["scale"], input_spec["quantization"]["zeroPoint"]
    if (race_input["quantization"]["scale"], race_input["quantization"]["zero_point"]) != (scale, zero_point):
        raise ValueError("the two exports quantize the input differently")

    merged = merge_models(species.model_bytes, basic_race.model_bytes, BASIC_RACE_TENSOR_PREFIX)

    species_fixtures = json.loads((species_fixtures_dir / FIXTURE_EXPECTATIONS_FILE).read_text(encoding="utf-8"))
    species_images = np.stack([_read_png(species_fixtures_dir / entry["image"]) for entry in species_fixtures["fixtures"]])
    race_images = np.stack([load_model_input(data_root / photo.image_path, race_input["sizePx"]) for photo in race_verification_photos])
    verify_merged_outputs(
        merged,
        [species.model_bytes, basic_race.model_bytes],
        quantize_input(np.concatenate([species_images, race_images]), scale, zero_point),
    )

    model_name, metadata_name = model_file_names(version)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / model_name
    model_path.write_bytes(merged)
    runner = _MergedRunner(merged, scale, zero_point)

    metadata = _bundle_metadata(species, basic_race, version, sha256_of_file(model_path))
    write_metadata(metadata, out_dir / metadata_name)

    _write_species_fixtures(species_fixtures, species_fixtures_dir, species_images, runner, version, fixtures_root / "species")
    _write_basic_race_fixtures(
        race_test_photos, image_records, data_root, runner, metadata["heads"][BASIC_RACE_HEAD_ID], version,
        fixtures_root / "basic-race", race_fixture_count_per_race, race_input["sizePx"],
    )
    return metadata


def _bundle_metadata(species: SourceExport, basic_race: SourceExport, version: int, model_sha256: str) -> dict:
    """The species metadata with a new version, the basicRace head and both source models recorded."""
    metadata = copy.deepcopy(species.metadata)
    race = basic_race.metadata
    gate_rule = race["operatingPoints"][f"{GATE_COVERAGE:.2f}"]["rule"]
    evaluation = {key: value for key, value in race.items() if key not in ("provenance", "temperatures")}
    model_file, _ = model_file_names(version)
    metadata.update(
        {
            "modelVersion": version,
            "modelFile": model_file,
            "createdOn": datetime.date.today().isoformat(),
            "backbone": "MobileNetV2 1.0 (ImageNet weights), one fine-tuned network per output (ADR-0012)",
            "headOrder": [SPECIES_HEAD_ID, BASIC_RACE_HEAD_ID],
        }
    )
    metadata["heads"][BASIC_RACE_HEAD_ID] = basic_race_head(
        output_index=BASIC_RACE_OUTPUT_INDEX,
        races=race["races"],
        temperature=race["temperatures"]["int8"],
        group_probability_mass=gate_rule["group_probability_mass"],
        max_group_size=gate_rule["max_group_size"],
        meets_accuracy_goal=False,
        status=BASIC_RACE_STATUS,
        evaluation=evaluation,
        source_model={
            "file": basic_race.model_path.name,
            "modelVersion": race["modelVersion"],
            "modelFileSha256": race["provenance"]["modelFileSha256"],
            "provenance": race["provenance"],
        },
    )
    metadata["trainingData"] = metadata["trainingData"] | {
        "modelFileSha256": model_sha256,
        "sourceModels": {
            SPECIES_HEAD_ID: {"file": species.model_path.name, "modelFileSha256": species.metadata["trainingData"]["modelFileSha256"]},
            BASIC_RACE_HEAD_ID: {"file": basic_race.model_path.name, "modelFileSha256": race["provenance"]["modelFileSha256"]},
        },
        "merge": "structural (model_bundle.merge_models): outputs bit-identical to each source model",
    }
    return metadata


class _MergedRunner:
    """The merged model with the reference kernels, as the export's expected outputs are made."""

    def __init__(self, model_bytes: bytes, scale: float, zero_point: int) -> None:
        self._interpreter = tf.lite.Interpreter(
            model_content=model_bytes,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
        )
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        self._outputs = self._interpreter.get_output_details()
        self._scale, self._zero_point = scale, zero_point

    def outputs(self, image: np.ndarray) -> list[np.ndarray]:
        self._interpreter.set_tensor(self._input["index"], quantize_input(image, self._scale, self._zero_point)[np.newaxis])
        self._interpreter.invoke()
        return [self._interpreter.get_tensor(output["index"])[0].copy() for output in self._outputs]

    def logit_step(self, output_index: int):
        return logit_quantization_step(
            self._outputs[output_index],
            self._interpreter.get_tensor_details(),
            self._interpreter._get_ops_details(),  # no public API lists the ops
        )


def _write_species_fixtures(source: dict, source_dir: Path, images: np.ndarray, runner: _MergedRunner, version: int, target: Path) -> None:
    """The source export's species fixtures, re-recorded for the bundle version.

    The merge is bit-identical, so the logits must equal the recorded ones exactly. Anything
    else means the fixtures do not belong to the species model inside the bundle.
    """
    target.mkdir(parents=True, exist_ok=True)
    for entry, image in zip(source["fixtures"], images, strict=True):
        species_logits = runner.outputs(image)[SPECIES_OUTPUT_INDEX]
        if not np.array_equal(species_logits, np.array(entry["logits"], dtype=np.float32)):
            raise ValueError(f"{entry['image']}: the bundle's species logits differ from the recorded fixture")
        if source_dir.resolve() != target.resolve():
            shutil.copyfile(source_dir / entry["image"], target / entry["image"])
    document = source | {"modelVersion": version}
    (target / FIXTURE_EXPECTATIONS_FILE).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _write_basic_race_fixtures(
    test_photos: Sequence[RacePhoto],
    image_records: dict[str, CultivarImageRecord],
    data_root: Path,
    runner: _MergedRunner,
    head: dict,
    version: int,
    target: Path,
    count_per_race: int,
    input_size_px: int,
) -> None:
    """Test photos at input size with the basicRace logits, probabilities and answer.

    Taken round-robin over races in split order, then topped up with the first photo answered
    with a two-race group and the first "unrecognized" one if the round-robin has neither, so
    the phones' parity tests cover every kind of answer.
    """
    races = head["races"]
    rule = RaceEvaluationSettings(
        group_probability_mass=head["answerRule"]["groupProbabilityMass"],
        max_group_size=head["answerRule"]["maxGroupSize"],
    )

    def answer_of(photo: RacePhoto) -> tuple[np.ndarray, np.ndarray, tuple[str, ...] | None, np.ndarray]:
        image = load_model_input(data_root / photo.image_path, input_size_px)
        logits = runner.outputs(image)[BASIC_RACE_OUTPUT_INDEX]
        probabilities = softmax(logits[np.newaxis], head["temperature"])[0]
        return image, logits, returned_group(probabilities, races, rule), probabilities

    chosen: list[RacePhoto] = []
    for race in races:
        chosen += [photo for photo in test_photos if photo.race == race][:count_per_race]
    answers = {photo.image_path: answer_of(photo) for photo in chosen}
    for wanted in ("pair", "unrecognized"):
        if any(_answer_kind(answer[2]) == wanted for answer in answers.values()):
            continue
        for photo in test_photos:
            if photo.image_path in answers:
                continue
            answer = answer_of(photo)
            if _answer_kind(answer[2]) == wanted:
                chosen.append(photo)
                answers[photo.image_path] = answer
                break

    if target.exists():
        for old in target.glob("basic-race-*.png"):
            old.unlink()
    target.mkdir(parents=True, exist_ok=True)
    expectations = []
    for photo in chosen:
        image, logits, group, probabilities = answers[photo.image_path]
        record = image_records[photo.image_path]
        # The checksum keeps two plantings' photos of one accession apart.
        file_name = f"basic-race-{photo.race}-{photo.accession.replace(' ', '')}-{photo.sha256[:8]}.png"
        Image.fromarray(image).save(target / file_name)
        expectations.append(
            {
                "image": file_name,
                "race": photo.race,
                "logits": logits.tolist(),
                "probabilities": probabilities.tolist(),
                # The races the shared answer rule must return, most likely first; null is "unrecognized".
                "answer": list(group) if group is not None else None,
                "license": record.license,
                "attribution": record.attribution,
            }
        )
    step = runner.logit_step(BASIC_RACE_OUTPUT_INDEX)
    if step is None:
        raise ValueError("the basicRace output has no int8 logit tensor to take the parity step from")
    document = {
        "modelVersion": version,
        "head": BASIC_RACE_HEAD_ID,
        "outputIndex": BASIC_RACE_OUTPUT_INDEX,
        **logit_tolerance_fields(step),
        "fixtures": expectations,
    }
    (target / FIXTURE_EXPECTATIONS_FILE).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _answer_kind(group: tuple[str, ...] | None) -> str:
    if group is None:
        return "unrecognized"
    return "single" if len(group) == 1 else "pair"


def _read_png(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
