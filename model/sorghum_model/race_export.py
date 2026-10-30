"""Exports a race run to INT8 and scores it once on the untouched test split (T9, #32).

Needs the `export` extra (TensorFlow 2.17, `ExportSettings.converter_tensorflow_version`).
Order follows the species export (CLAUDE.md, ML hygiene): quantize to INT8 first, then fit
the temperature and choose the answer rules on the INT8 outputs of the validation split, the
outputs the phones would see. Test is touched once, at the end, with everything fixed.

Writes `race-vN.tflite`, `race-vN.json` (every number below) and `race-vN-report.txt`
(per-race support, recall and confusion). These are research artifacts for the gate: the
app does not load them, and the `traits-vN` contract is unchanged.
"""

import datetime
import json
from collections.abc import Sequence
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model.calibration import expected_calibration_error, fit_temperature, softmax
from sorghum_model.export import TfliteRunner, convert_to_int8
from sorghum_model.manifest import sha256_of_file
from sorghum_model.preprocessing import load_model_input
from sorghum_model.race_evaluation import (
    RaceEvaluation,
    choose_answer_rule,
    evaluate_basic_races,
    evaluate_races,
    majority_race_probabilities,
    planting_race_probabilities,
    planting_shortcut_check,
    race_evaluation_report,
    race_gate_problems,
    top1_accuracy,
)
from sorghum_model.race_photos import RacePhoto, photos_in, race_class_names
from sorghum_model.race_training import RACE_MODEL_FILE
from sorghum_model.settings import (
    MODEL_INPUT_SIZE_PX,
    ExportSettings,
    RaceEvaluationSettings,
    RaceGateSettings,
    RaceRuleSearchSettings,
)
from sorghum_model.splits import Split
from sorghum_model.train import SHUFFLE_SEED

# The gate's coverage, and the second operating point #32 asks to report.
GATE_COVERAGE = 0.80
SECOND_COVERAGE = 0.90


def export_race_model(
    run_dir: Path,
    photos: list[RacePhoto],
    data_root: Path,
    version: int,
    output_dir: Path,
    export_settings: ExportSettings,
    search: RaceRuleSearchSettings,
    gate: RaceGateSettings,
    provenance: dict,
) -> dict:
    """Writes the INT8 model, its evaluation and report; returns the evaluation document."""
    races = race_class_names(photos)
    train, validation, test = (photos_in(photos, split) for split in Split)
    float_model = keras.models.load_model(run_dir / RACE_MODEL_FILE)
    representative = [train[i] for i in np.random.default_rng(SHUFFLE_SEED).permutation(len(train))]
    model_bytes = convert_to_int8(
        float_model, _load_inputs(representative[: export_settings.representative_images], data_root)
    )
    runner = TfliteRunner(model_bytes)

    validation_images = _load_inputs(validation, data_root)
    test_images = _load_inputs(test, data_root)
    logits = {
        ("float", Split.VALIDATION): float_model.predict(validation_images.astype(np.float32), verbose=0),
        ("float", Split.TEST): float_model.predict(test_images.astype(np.float32), verbose=0),
        ("int8", Split.VALIDATION): runner.logits(validation_images),
        ("int8", Split.TEST): runner.logits(test_images),
    }
    validation_labels = _labels(validation, races)
    temperatures = {
        kind: fit_temperature(logits[(kind, Split.VALIDATION)], validation_labels) for kind in ("float", "int8")
    }
    probabilities = {key: softmax(value, temperatures[key[0]]) for key, value in logits.items()}

    operating_points = {}
    gate_evaluations = {}
    for target in (GATE_COVERAGE, SECOND_COVERAGE):
        # Chosen on the INT8 validation outputs only; the float model is scored with the same
        # rule, so the delta is the quantization's alone.
        try:
            chosen = choose_answer_rule(
                [p.race for p in validation], [p.accession for p in validation],
                probabilities[("int8", Split.VALIDATION)], races, target, search,
            )
        except ValueError as error:
            if target == GATE_COVERAGE:
                raise
            # Groups of at most three races may not cover 90% of photos; say so, not a crash.
            operating_points[f"{target:.2f}"] = {"reachable": False, "reason": str(error)}
            continue
        int8_test = _score(test, probabilities[("int8", Split.TEST)], races, chosen.settings)
        float_test = _score(test, probabilities[("float", Split.TEST)], races, chosen.settings)
        operating_points[f"{target:.2f}"] = {
            "rule": chosen.settings.__dict__,
            "validationInt8": _summary(chosen.validation),
            "testInt8": _summary(int8_test),
            "testFloat": _summary(float_test),
            # SECONDARY, never the gate: the same answers read at basic-race level.
            "secondaryBasicRaceTestInt8": _basic_summary(
                evaluate_basic_races([p.race for p in test], probabilities[("int8", Split.TEST)], races, chosen.settings)
            ),
        }
        gate_evaluations[target] = (int8_test, float_test)
        if target == GATE_COVERAGE:
            int8_gate_rule = chosen.settings

    train_races = [p.race for p in train]
    baseline_rule = RaceEvaluationSettings()  # one-hot rows: every rule answers with one race
    majority = _score(test, majority_race_probabilities(train_races, races, len(test)), races, baseline_rule)
    planting = _score(
        test,
        planting_race_probabilities(train_races, [p.planting_id for p in train], [p.planting_id for p in test], races),
        races,
        baseline_rule,
    )
    best_baseline = max(majority.accuracy, planting.accuracy)
    int8_gate_test, float_gate_test = gate_evaluations[GATE_COVERAGE]
    problems = race_gate_problems(int8_gate_test, float_gate_test, best_baseline, gate)

    test_labels = _labels(test, races)
    test_truth = [p.race for p in test]
    document = {
        "modelVersion": version,
        "createdOn": datetime.date.today().isoformat(),
        "converterTensorflowVersion": tf.__version__,
        "races": list(races),
        "input": {"sizePx": MODEL_INPUT_SIZE_PX, "quantization": runner.input_quantization.__dict__},
        "temperatures": temperatures,
        "photos": {split.value: len(photos_in(photos, split)) for split in Split},
        "operatingPoints": operating_points,
        "testTop1": {kind: top1_accuracy(test_truth, probabilities[(kind, Split.TEST)], races) for kind in ("float", "int8")},
        "testEce": {
            kind: {
                "beforeTemperature": expected_calibration_error(
                    softmax(logits[(kind, Split.TEST)]), test_labels, export_settings.ece_bins
                ),
                "afterTemperature": expected_calibration_error(
                    probabilities[(kind, Split.TEST)], test_labels, export_settings.ece_bins
                ),
            }
            for kind in ("float", "int8")
        },
        "testBaselines": {"majority": _summary(majority), "planting": _summary(planting)},
        "plantingShortcutCheck": {
            split.value: [
                check.__dict__ | {"gainOverBaseline": check.gain_over_baseline}
                for check in planting_shortcut_check(
                    [p.race for p in scored], [p.accession for p in scored], [p.planting_id for p in scored],
                    probabilities[("int8", split)], races, int8_gate_rule, train_races, [p.planting_id for p in train],
                )
            ]
            for split, scored in ((Split.VALIDATION, validation), (Split.TEST, test))
        },
        "gate": gate.__dict__ | {"problems": problems, "passed": not problems},
        "provenance": provenance,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"race-v{version}.tflite"
    model_path.write_bytes(model_bytes)
    document["provenance"] = provenance | {"modelFileSha256": sha256_of_file(model_path)}
    (output_dir / f"race-v{version}.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    report = [f"race-v{version}: INT8 on test at the {GATE_COVERAGE:.2f}-coverage rule"]
    report += race_evaluation_report(int8_gate_test, races)
    if SECOND_COVERAGE in gate_evaluations:
        report += [f"INT8 on test at the {SECOND_COVERAGE:.2f}-coverage rule"]
        report += race_evaluation_report(gate_evaluations[SECOND_COVERAGE][0], races)
    report += ["majority baseline on test"] + race_evaluation_report(majority, races)[:1]
    report += ["planting baseline on test"] + race_evaluation_report(planting, races)[:1]
    report += ["gate: " + ("passed" if not problems else "; ".join(problems))]
    (output_dir / f"race-v{version}-report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return document


def _load_inputs(photos: Sequence[RacePhoto], data_root: Path) -> np.ndarray:
    """(n, 224, 224, 3) uint8 model inputs, with the shared preprocessing."""
    return np.stack([load_model_input(data_root / p.image_path, MODEL_INPUT_SIZE_PX) for p in photos])


def _labels(photos: Sequence[RacePhoto], races: tuple[str, ...]) -> np.ndarray:
    return np.array([races.index(p.race) for p in photos], dtype=np.int64)


def _score(photos, probabilities, races, settings) -> RaceEvaluation:
    return evaluate_races([p.race for p in photos], [p.accession for p in photos], probabilities, races, settings)


def _summary(evaluation: RaceEvaluation) -> dict:
    return {
        "photos": evaluation.photo_count,
        "coverage": evaluation.coverage,
        "selectiveAccuracy": evaluation.selective_accuracy,
        "accuracyOverAllPhotos": evaluation.accuracy,
        "meanGroupSize": evaluation.mean_group_size,
        "inGroupRecallByRace": {
            race: evaluation.hits_by_race.get(race, 0) / photos for race, (photos, _) in sorted(evaluation.support.items())
        },
        "supportByRace": {race: {"photos": p, "accessions": a} for race, (p, a) in sorted(evaluation.support.items())},
    }


def _basic_summary(evaluation) -> dict:
    return {
        "rule": "hit when a parent basic race of the true race is among the parents of the returned group",
        "photos": evaluation.photo_count,
        "coverage": evaluation.coverage,
        "selectiveAccuracy": evaluation.selective_accuracy,
    }
