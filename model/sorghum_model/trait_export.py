"""Exports a trait-head run to INT8 and scores every head once on the untouched test split
(T12, #35). Needs the `export` extra (TensorFlow 2.17, `ExportSettings.converter_tensorflow_version`).

Order as the species and race exports (CLAUDE.md, ML hygiene): quantize to INT8 first, then
fit one temperature per head on the INT8 outputs of the validation split, then score test
once with everything fixed. Each head is gated on its own (`TraitGateSettings`, risk R6).

Writes `trait-heads-vN.tflite`, `trait-heads-vN.json` (heads by output index, state order,
temperatures, every number below, gate verdicts), `trait-heads-vN-report.txt` (per-state
support, recall and confusion) and `trait-heads-vN-outputs.npz` (calibrated INT8
probabilities of every validation and test photo, for the offline ranking check). These are
research artifacts: the app does not load them and the `traits-vN` contract is unchanged.
"""

import datetime
import json
from collections.abc import Sequence
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model.calibration import expected_calibration_error, fit_temperature, softmax
from sorghum_model.cultivar_traits import TraitPhoto
from sorghum_model.export import TfliteRunner, convert_to_int8, xnnpack_load_error
from sorghum_model.manifest import sha256_of_file
from sorghum_model.preprocessing import load_model_input
from sorghum_model.race_evaluation import majority_race_probabilities, planting_race_probabilities
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, ExportSettings, TraitGateSettings
from sorghum_model.splits import Split
from sorghum_model.train import SHUFFLE_SEED
from sorghum_model.trait_evaluation import (
    TraitEvaluation,
    evaluate_trait,
    match_heads_to_outputs,
    trait_evaluation_report,
    trait_gate_problems,
)
from sorghum_model.trait_training import TRAIT_MODEL_FILE


def export_trait_model(
    run_dir: Path,
    photos: list[TraitPhoto],
    head_states: dict[str, tuple[str, ...]],
    data_root: Path,
    version: int,
    output_dir: Path,
    export_settings: ExportSettings,
    gate: TraitGateSettings,
    provenance: dict,
) -> dict:
    """Writes the INT8 model, its evaluation, report and outputs; returns the evaluation document."""
    labelled = [p for p in photos if any(p.states.get(t) in states for t, states in head_states.items())]
    train = [p for p in labelled if p.split is Split.TRAIN]
    # Every validation and test photo is run, labelled or not, so the saved outputs also serve
    # the race ranking check; each head is scored only on photos with one of its states.
    validation, test = ([p for p in photos if p.split is split] for split in (Split.VALIDATION, Split.TEST))
    float_model = keras.models.load_model(run_dir / TRAIT_MODEL_FILE)
    representative = [train[i] for i in np.random.default_rng(SHUFFLE_SEED).permutation(len(train))]
    model_bytes = convert_to_int8(
        float_model, _load_inputs(representative[: export_settings.representative_images], data_root)
    )
    runner = TfliteRunner(model_bytes)

    images = {Split.VALIDATION: _load_inputs(validation, data_root), Split.TEST: _load_inputs(test, data_root)}
    float_logits = {
        split: {head: np.asarray(logits) for head, logits in float_model.predict(batch.astype(np.float32), verbose=0).items()}
        for split, batch in images.items()
    }
    int8_by_output = {split: runner.logits_of_every_output(batch) for split, batch in images.items()}
    output_index = match_heads_to_outputs(float_logits[Split.VALIDATION], int8_by_output[Split.VALIDATION])
    int8_logits = {
        split: {head: outputs[output_index[head]] for head in head_states} for split, outputs in int8_by_output.items()
    }
    split_photos = {Split.VALIDATION: validation, Split.TEST: test}

    heads = {}
    saved_outputs: dict[str, np.ndarray] = {}
    report = [f"trait-heads-v{version}: INT8 on test, temperature fitted on INT8 validation"]
    for head, states in head_states.items():
        rows = {split: _rows_with_state(split_photos[split], head, states) for split in split_photos}
        validation_labels = _labels(validation, rows[Split.VALIDATION], head, states)
        temperatures = {
            kind: fit_temperature(logits[Split.VALIDATION][head][rows[Split.VALIDATION]], validation_labels)
            for kind, logits in (("float", float_logits), ("int8", int8_logits))
        }

        def score(kind: str, split: Split, temperature: float | None) -> TraitEvaluation:
            logits = (float_logits if kind == "float" else int8_logits)[split][head][rows[split]]
            probabilities = softmax(logits) if temperature is None else softmax(logits, temperature)
            scored = [split_photos[split][i] for i in rows[split]]
            return evaluate_trait(
                [p.states[head] for p in scored], [p.accession for p in scored], probabilities, states,
                export_settings.ece_bins,
            )

        int8_test = score("int8", Split.TEST, temperatures["int8"])
        float_test = score("float", Split.TEST, temperatures["float"])
        test_scored = [test[i] for i in rows[Split.TEST]]
        train_scored = [p for p in train if p.states.get(head) in states]
        baselines = _baselines(train_scored, test_scored, head, states, export_settings.ece_bins)
        best_baseline = max(b.accuracy for b in baselines.values())
        problems = trait_gate_problems(int8_test, float_test, best_baseline, gate)
        heads[head] = {
            "outputIndex": output_index[head],
            "states": list(states),
            "temperature": temperatures["int8"],
            "floatTemperature": temperatures["float"],
            "photos": {split.value: len(rows[split]) for split in split_photos} | {"train": len(train_scored)},
            "validationInt8": _summary(score("int8", Split.VALIDATION, temperatures["int8"])),
            "testInt8": _summary(int8_test),
            "testInt8EceBeforeTemperature": score("int8", Split.TEST, None).ece,
            "testFloat": _summary(float_test),
            "testBaselines": {name: _summary(evaluation) for name, evaluation in baselines.items()},
            "gate": {"problems": problems, "passed": not problems},
        }
        report += ["", f"{head}: gate " + ("passed" if not problems else "missed: " + "; ".join(problems))]
        report += trait_evaluation_report(int8_test, states)
        report += [f"baselines on test: " + ", ".join(f"{n} {b.accuracy:.3f}" for n, b in baselines.items())]
        for split in split_photos:
            saved_outputs[f"{head}/{split.value}"] = softmax(int8_logits[split][head], temperatures["int8"])

    document = {
        "modelVersion": version,
        "createdOn": datetime.date.today().isoformat(),
        "converterTensorflowVersion": tf.__version__,
        "loadsWithXnnpack": xnnpack_load_error(model_bytes) is None,
        "input": {"sizePx": MODEL_INPUT_SIZE_PX, "quantization": runner.input_quantization.__dict__},
        "heads": heads,
        "gate": gate.__dict__,
        "passedHeads": [head for head, result in heads.items() if result["gate"]["passed"]],
        "provenance": provenance,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"trait-heads-v{version}.tflite"
    model_path.write_bytes(model_bytes)
    document["provenance"] = provenance | {"modelFileSha256": sha256_of_file(model_path)}
    (output_dir / f"trait-heads-v{version}.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (output_dir / f"trait-heads-v{version}-report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    np.savez(
        output_dir / f"trait-heads-v{version}-outputs.npz",
        **saved_outputs,
        **{f"sha256/{split.value}": np.array([p.sha256 for p in split_photos[split]]) for split in split_photos},
    )
    return document


def _rows_with_state(photos: Sequence[TraitPhoto], head: str, states: Sequence[str]) -> list[int]:
    """Indices of the photos whose accession has a state this head outputs."""
    return [i for i, p in enumerate(photos) if p.states.get(head) in states]


def _labels(photos: Sequence[TraitPhoto], rows: list[int], head: str, states: Sequence[str]) -> np.ndarray:
    return np.array([list(states).index(photos[i].states[head]) for i in rows], dtype=np.int64)


def _baselines(train, test, head, states, ece_bins) -> dict[str, TraitEvaluation]:
    """Majority-state and planting baselines on the test photos, from training labels only."""
    train_states = [p.states[head] for p in train]
    test_states = [p.states[head] for p in test]
    accessions = [p.accession for p in test]
    probabilities = {
        "majority": majority_race_probabilities(train_states, states, len(test)),
        "planting": planting_race_probabilities(
            train_states, [p.planting_id for p in train], [p.planting_id for p in test], states
        ),
    }
    return {name: evaluate_trait(test_states, accessions, p, states, ece_bins) for name, p in probabilities.items()}


def _load_inputs(photos: Sequence[TraitPhoto], data_root: Path) -> np.ndarray:
    """(n, 224, 224, 3) uint8 model inputs, with the shared preprocessing."""
    return np.stack([load_model_input(data_root / p.image_path, MODEL_INPUT_SIZE_PX) for p in photos])


def _summary(evaluation: TraitEvaluation) -> dict:
    return {
        "photos": evaluation.photo_count,
        "accuracy": evaluation.accuracy,
        "macroRecall": evaluation.macro_recall,
        "ece": evaluation.ece,
        "recallByState": evaluation.recall_by_state,
        "supportByState": {state: {"photos": p, "accessions": a} for state, (p, a) in sorted(evaluation.support.items())},
    }
