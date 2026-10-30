"""Trains the race head (T9, #32) on the traits-v2 MobileNetV2 backbone. Needs the `train` extra.

The backbone is taken from a trained species run (`species.keras`, traits-v2), with its
weights, so the race head starts from features already tuned to sorghum photos. The model
takes the same 0-255 uint8 224 px input as the species head and outputs one logit per race,
in `race_photos.race_class_names` order. Training reuses the species schedule
(`train.fit_in_two_phases`): head first on the frozen backbone, then fine-tuning from
`RaceTrainingSettings.first_fine_tuned_layer` on with BatchNorm frozen.

The race model is a separate model for now: fine-tuning changes the backbone, so the species
head no longer fits it. Folding race into the shipped multi-head model (ADR-0006) is a later
step, only if the race model passes its gate.
"""

import json
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model.race_photos import (
    RacePhoto,
    balanced_race_weights,
    photos_in,
    race_class_names,
    undersized_races,
)
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, RaceTrainingSettings
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

RACE_MODEL_FILE = "race.keras"
RACE_TRAINING_REPORT_FILE = "race_training_report.json"
RACE_HEAD_NAME = "race"


def train_race_model(
    photos: list[RacePhoto],
    data_root: Path,
    starting_model: Path,
    run_dir: Path,
    settings: RaceTrainingSettings,
    resume: bool = False,
) -> Path:
    """Trains, saves the best model (`race.keras`) and the training report; returns `run_dir`.

    `starting_model` is the species run's `species.keras` whose backbone the race head
    starts from. With `resume`, continues after the last finished epoch.
    """
    races = race_class_names(photos)
    problems = undersized_races(
        photos, races, settings.min_train_photos_per_race, settings.min_evaluation_photos_per_race
    )
    if problems:
        raise ValueError("Not enough photos to train every race:\n  " + "\n  ".join(problems))
    refuse_unfinished_run_without_resume(run_dir, resume)
    run_dir.mkdir(parents=True, exist_ok=True)
    keras.utils.set_random_seed(SHUFFLE_SEED)

    train = photos_in(photos, Split.TRAIN)
    shuffled_train = [train[i] for i in np.random.default_rng(SHUFFLE_SEED).permutation(len(train))]
    validation = photos_in(photos, Split.VALIDATION)
    cache_dir = run_dir / INPUT_CACHE_DIR
    remove_stale_cache_locks(cache_dir)
    train_data = make_dataset(
        [data_root / p.image_path for p in shuffled_train], race_indices(shuffled_train, races),
        [p.sha256 for p in shuffled_train], settings.batch_size, cache_dir, "train", is_training=True,
    )
    validation_data = make_dataset(
        [data_root / p.image_path for p in validation], race_indices(validation, races),
        [p.sha256 for p in validation], settings.batch_size, cache_dir, "validation", is_training=False,
    )

    model, backbone = build_race_model(starting_model, len(races), settings.dropout)
    class_weight = balanced_race_weights(train, races) if settings.balanced_class_weights else None
    fit_in_two_phases(
        model, backbone, train_data, validation_data, class_weight,
        run_dir, RACE_MODEL_FILE, settings,
    )
    _write_training_report(run_dir, photos, races, settings, starting_model)
    return run_dir


def build_race_model(starting_model: Path, race_count: int, dropout: float) -> tuple[keras.Model, keras.Model]:
    """Returns (model, backbone): the starting model's backbone, with its weights, under a new
    race head. Input scaling to [-1, 1] is inside the graph, as in the species model."""
    species_model = keras.models.load_model(starting_model)
    backbones = [layer for layer in species_model.layers if isinstance(layer, keras.Model)]
    if len(backbones) != 1:
        raise ValueError(f"{starting_model} should hold exactly one backbone model, found {len(backbones)}")
    backbone = backbones[0]
    size = MODEL_INPUT_SIZE_PX
    inputs = keras.Input(shape=(size, size, 3), name="image")
    scaled = keras.layers.Rescaling(1 / 127.5, offset=-1, name="to_minus_one_one")(inputs)
    # training=False keeps BatchNorm statistics frozen while fine-tuning (see train.py).
    features = backbone(scaled, training=False)
    features = keras.layers.Dropout(dropout)(features)
    logits = keras.layers.Dense(race_count, name=RACE_HEAD_NAME)(features)
    return keras.Model(inputs, logits, name="sorghum_race_model"), backbone


def race_indices(photos: list[RacePhoto], races: tuple[str, ...]) -> np.ndarray:
    """Head output index of each photo's race."""
    return np.array([races.index(photo.race) for photo in photos], dtype=np.int64)


def _write_training_report(
    run_dir: Path, photos: list[RacePhoto], races: tuple[str, ...], settings: RaceTrainingSettings,
    starting_model: Path,
) -> None:
    head_history, fine_tune_history = history_by_phase(read_history(run_dir / HISTORY_FILE), settings.head_epochs)
    report = {
        "settings": settings.__dict__,
        "startingModel": str(starting_model),
        "tensorflowVersion": tf.__version__,
        "races": list(races),
        "photosPerRaceAndSplit": {
            f"{race}/{split.value}": sum(1 for p in photos if p.race == race and p.split is split)
            for race in races
            for split in Split
        },
        "headHistory": head_history,
        "fineTuneHistory": fine_tune_history,
    }
    (run_dir / RACE_TRAINING_REPORT_FILE).write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
