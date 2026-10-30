"""Trains the learned trait heads (T12, #35) on the traits-v2 MobileNetV2 backbone. Needs the
`train` extra.

One model, one backbone, one softmax head per trait (ADR-0004, ADR-0006), each over the
trait's head states (`cultivar_traits.head_states`) in catalogue order. A photo trains every
head its accession has a state for; for the other heads its loss weight is 0, so one photo
with a glume colour but no grain colour still teaches the glume head. Training reuses the
species schedule (`train.fit_in_two_phases`); with `fine_tune_epochs = 0` the backbone stays
the traits-v2 one, so the heads can later sit next to the species head in one model without
changing its outputs.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model.cultivar_traits import TraitPhoto
from sorghum_model.race_training import backbone_features
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, TraitTrainingSettings
from sorghum_model.splits import Split
from sorghum_model.train import (
    INPUT_CACHE_DIR,
    SHUFFLE_SEED,
    fit_in_two_phases,
    make_dataset,
    refuse_unfinished_run_without_resume,
    remove_stale_cache_locks,
)
from sorghum_model.training_history import HISTORY_FILE, history_by_phase, read_history

TRAIT_MODEL_FILE = "traits.keras"
TRAIT_TRAINING_REPORT_FILE = "trait_training_report.json"
# Label of a photo for a head its accession has no state for; trained with loss weight 0.
NO_STATE = -1


def train_trait_model(
    photos: list[TraitPhoto],
    head_states: dict[str, tuple[str, ...]],
    data_root: Path,
    starting_model: Path,
    run_dir: Path,
    settings: TraitTrainingSettings,
    resume: bool = False,
) -> Path:
    """Trains, saves the best model (`traits.keras`) and the training report; returns `run_dir`.

    `head_states` maps each trait id to its head's output states. Only photos with a state
    for at least one head are used. `starting_model` is the species run's `species.keras`.
    """
    if not head_states or any(len(states) < 2 for states in head_states.values()):
        raise ValueError(f"every head needs at least two states: {head_states}")
    refuse_unfinished_run_without_resume(run_dir, resume)
    run_dir.mkdir(parents=True, exist_ok=True)
    keras.utils.set_random_seed(SHUFFLE_SEED)

    labelled = [p for p in photos if any(p.states.get(t) in states for t, states in head_states.items())]
    train = [p for p in labelled if p.split is Split.TRAIN]
    shuffled_train = [train[i] for i in np.random.default_rng(SHUFFLE_SEED).permutation(len(train))]
    validation = [p for p in labelled if p.split is Split.VALIDATION]
    cache_dir = run_dir / INPUT_CACHE_DIR
    remove_stale_cache_locks(cache_dir)
    train_data, validation_data = (
        with_missing_states_masked(
            make_dataset(
                [data_root / p.image_path for p in subset], state_indices(subset, head_states),
                [p.sha256 for p in subset], settings.batch_size, cache_dir, name, is_training=name == "train",
            )
        )
        for subset, name in ((shuffled_train, "train"), (validation, "validation"))
    )

    model, backbone = build_trait_model(starting_model, head_states, settings.dropout)
    fit_in_two_phases(
        model, backbone, train_data, validation_data, None, run_dir, TRAIT_MODEL_FILE, settings,
        metrics={trait_id: [] for trait_id in head_states},
    )
    _write_training_report(run_dir, labelled, head_states, settings, starting_model)
    return run_dir


def build_trait_model(
    starting_model: Path, head_states: dict[str, tuple[str, ...]], dropout: float
) -> tuple[keras.Model, keras.Model]:
    """Returns (model, backbone): the starting model's backbone, with its weights, under one
    logit head per trait (outputs named by trait id). Input as the species model: 0-255 RGB."""
    inputs, features, backbone = backbone_features(starting_model, dropout)
    outputs = {
        trait_id: keras.layers.Dense(len(states), name=trait_id)(features) for trait_id, states in head_states.items()
    }
    return keras.Model(inputs, outputs, name="sorghum_trait_model"), backbone


def state_indices(photos: Sequence[TraitPhoto], head_states: dict[str, tuple[str, ...]]) -> dict[str, np.ndarray]:
    """Per head, each photo's output index, or NO_STATE when its accession has no head state."""
    return {
        trait_id: np.array(
            [states.index(p.states[trait_id]) if p.states.get(trait_id) in states else NO_STATE for p in photos],
            dtype=np.int64,
        )
        for trait_id, states in head_states.items()
    }


def with_missing_states_masked(dataset: tf.data.Dataset) -> tf.data.Dataset:
    """(image, labels) -> (image, labels, sample weights): NO_STATE labels become index 0
    with weight 0, so they add nothing to the loss."""
    return dataset.map(
        lambda image, labels: (
            image,
            {trait_id: tf.maximum(label, 0) for trait_id, label in labels.items()},
            {trait_id: tf.cast(label >= 0, tf.float32) for trait_id, label in labels.items()},
        )
    )


def _write_training_report(
    run_dir: Path, photos: list[TraitPhoto], head_states: dict[str, tuple[str, ...]],
    settings: TraitTrainingSettings, starting_model: Path,
) -> None:
    head_history, fine_tune_history = history_by_phase(read_history(run_dir / HISTORY_FILE), settings.head_epochs)
    report = {
        "settings": settings.__dict__,
        "startingModel": str(starting_model),
        "tensorflowVersion": tf.__version__,
        "inputSizePx": MODEL_INPUT_SIZE_PX,
        "headStates": {trait_id: list(states) for trait_id, states in head_states.items()},
        "photosPerStateAndSplit": {
            f"{trait_id}/{state}/{split.value}": sum(
                1 for p in photos if p.split is split and p.states.get(trait_id) == state
            )
            for trait_id, states in head_states.items()
            for state in states
            for split in Split
        },
        "headHistory": head_history,
        "fineTuneHistory": fine_tune_history,
    }
    (run_dir / TRAIT_TRAINING_REPORT_FILE).write_text(
        json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8"
    )
