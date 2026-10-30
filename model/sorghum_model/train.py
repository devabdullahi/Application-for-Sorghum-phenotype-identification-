"""Trains the species head (ADR-0006) on TrainingSettings.backbone. Needs the `train` extra (TensorFlow).

Two phases: first only the new head trains on a frozen ImageNet backbone, then the backbone
from `TrainingSettings.first_fine_tuned_layer` on fine-tunes at a lower rate. The checkpoint
with the lowest validation loss is kept. Every finished epoch is logged to `history.csv` and
its weights saved, so `resume=True` continues a run that died.
"""

import hashlib
import inspect
import json
from collections import Counter
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model import preprocessing
from sorghum_model.manifest import ImageRecord
from sorghum_model.preprocessing import load_model_input
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, Backbone, RaceTrainingSettings, TrainingSettings
from sorghum_model.species_classes import SPECIES_CLASS_NAMES
from sorghum_model.splits import Split, count_per_class_and_split, find_undersized_classes
from sorghum_model.training_history import (
    HISTORY_FILE,
    best_validation_loss,
    finished_epoch_count,
    history_by_phase,
    read_history,
)

# Fixed so two runs on the same manifests shuffle and augment the same way.
SHUFFLE_SEED = 1234

KERAS_MODEL_FILE = "species.keras"
TRAINING_REPORT_FILE = "training_report.json"
# Weights and optimizer state after the last finished epoch, for resuming.
LAST_EPOCH_WEIGHTS_FILE = "last_epoch.weights.h5"
# Decoded model inputs, so later epochs skip decoding full-size JPEGs from the data disk.
INPUT_CACHE_DIR = "input-cache"

# Decoded 224 px photos held for shuffling each epoch (about 300 MB). The cache stores the
# training photos in an order shuffled once with SHUFFLE_SEED, so this buffer only has to mix
# neighbours, not undo the manifests' per-source order.
SHUFFLE_BUFFER_IMAGES = 2048


def train_species_model(
    records: list[ImageRecord],
    splits: dict[str, Split],
    data_root: Path,
    run_dir: Path,
    settings: TrainingSettings,
    resume: bool = False,
) -> Path:
    """Trains, saves the best model and the training report, and returns `run_dir`.

    With `resume`, continues the run in `run_dir` after its last finished epoch (or starts it
    if none finished). Without it, refuses a `run_dir` that already holds a run, so two runs
    with different data or settings are never mixed. Resuming assumes the same records and
    settings.
    """
    counts = count_per_class_and_split(records, splits)
    problems = find_undersized_classes(
        counts,
        SPECIES_CLASS_NAMES,
        settings.min_train_images_per_class,
        settings.min_evaluation_images_per_class,
    )
    if problems:
        raise ValueError(
            "Not enough photos to train every species class:\n  "
            + "\n  ".join(problems)
            + "\nAdd photos (inat-download or import-folder) before training."
        )
    refuse_unfinished_run_without_resume(run_dir, resume)
    run_dir.mkdir(parents=True, exist_ok=True)
    keras.utils.set_random_seed(SHUFFLE_SEED)
    train_records = _records_in(records, splits, Split.TRAIN)
    validation_records = _records_in(records, splits, Split.VALIDATION)
    shuffled_train_records = [
        train_records[i] for i in np.random.default_rng(SHUFFLE_SEED).permutation(len(train_records))
    ]
    cache_dir = run_dir / INPUT_CACHE_DIR
    remove_stale_cache_locks(cache_dir)
    train_data = make_dataset(
        [data_root / r.image_path for r in shuffled_train_records],
        class_indices(shuffled_train_records),
        [r.sha256 for r in shuffled_train_records],
        settings.batch_size, cache_dir, "train", is_training=True,
    )
    validation_data = make_dataset(
        [data_root / r.image_path for r in validation_records],
        class_indices(validation_records),
        [r.sha256 for r in validation_records],
        settings.batch_size, cache_dir, "validation", is_training=False,
    )

    model, backbone = build_species_model(len(SPECIES_CLASS_NAMES), settings.dropout, settings.backbone)
    fit_in_two_phases(
        model, backbone, train_data, validation_data, _balanced_class_weights(train_records),
        run_dir, KERAS_MODEL_FILE, settings,
    )

    _write_training_report(
        run_dir / TRAINING_REPORT_FILE, counts, settings, read_history(run_dir / HISTORY_FILE)
    )
    return run_dir


def refuse_unfinished_run_without_resume(run_dir: Path, resume: bool) -> None:
    """Refuses a `run_dir` that already holds a run unless resuming, so two runs with
    different data or settings are never mixed in one history."""
    if (run_dir / HISTORY_FILE).exists() and not resume:
        raise ValueError(
            f"{run_dir} already holds a training run; pass --resume to continue it, "
            "or choose a new --run-dir"
        )


def fit_in_two_phases(
    model: keras.Model,
    backbone: keras.Model,
    train_data: tf.data.Dataset,
    validation_data: tf.data.Dataset,
    class_weight: dict[int, float] | None,
    run_dir: Path,
    model_file: str,
    settings: "TrainingSettings | RaceTrainingSettings",
) -> None:
    """Trains the head on a frozen backbone, then fine-tunes from `first_fine_tuned_layer` on.

    The model with the lowest validation loss is saved as `run_dir / model_file`. Every
    finished epoch is logged to `history.csv` and its weights saved, so a run that died
    continues after its last finished epoch (the caller checks `resume`).
    """
    history_path = run_dir / HISTORY_FILE
    frozen_in_fine_tune = _layers_before(backbone, settings.first_fine_tuned_layer)
    total_epochs = settings.head_epochs + settings.fine_tune_epochs
    finished = finished_epoch_count(read_history(history_path))
    last_weights = run_dir / LAST_EPOCH_WEIGHTS_FILE
    if finished and not last_weights.exists():
        raise ValueError(f"{history_path} logs {finished} epochs but {last_weights} is missing")

    def callbacks() -> list[keras.callbacks.Callback]:
        # Weights before the log line: an epoch that is logged always has its weights saved.
        return [
            keras.callbacks.ModelCheckpoint(
                run_dir / model_file,
                monitor="val_loss",
                save_best_only=True,
                # After a resume, only an epoch better than every earlier one replaces the best.
                initial_value_threshold=best_validation_loss(read_history(history_path)),
            ),
            keras.callbacks.ModelCheckpoint(last_weights, save_weights_only=True),
            keras.callbacks.CSVLogger(history_path, append=True),
        ]

    if finished < settings.head_epochs:
        backbone.trainable = False
        _compile(model, settings.head_learning_rate)
        if finished:
            _restore_with_optimizer(model, last_weights)
        model.fit(
            train_data,
            validation_data=validation_data,
            initial_epoch=finished,
            epochs=settings.head_epochs,
            class_weight=class_weight,
            callbacks=callbacks(),
        )
        finished = settings.head_epochs
    elif finished == settings.head_epochs:
        # The fine-tune phase has its own optimizer, so only the weights carry over.
        model.load_weights(last_weights)

    if finished < total_epochs:
        backbone.trainable = True
        for layer in frozen_in_fine_tune:
            layer.trainable = False
        _compile(model, settings.fine_tune_learning_rate)
        if finished > settings.head_epochs:
            _restore_with_optimizer(model, last_weights)
        model.fit(
            train_data,
            validation_data=validation_data,
            initial_epoch=finished,
            epochs=total_epochs,
            class_weight=class_weight,
            callbacks=callbacks(),
        )


def build_species_model(
    class_count: int, dropout: float, variant: Backbone
) -> tuple[keras.Model, keras.Model]:
    """Returns (model, backbone). The model takes 0-255 float RGB and outputs species logits.

    The backbone's own input scaling is inside the graph, so the device feeds raw pixel
    values and no normalisation constants live outside the model.
    """
    size = MODEL_INPUT_SIZE_PX
    inputs = keras.Input(shape=(size, size, 3), name="image")
    if variant is Backbone.MOBILENET_V2:
        backbone = keras.applications.MobileNetV2(
            input_shape=(size, size, 3),
            alpha=1.0,
            include_top=False,
            weights="imagenet",
            pooling="avg",
        )
        # MobileNetV2 has no include_preprocessing option; its weights expect [-1, 1].
        backbone_inputs = keras.layers.Rescaling(1 / 127.5, offset=-1, name="to_minus_one_one")(inputs)
    else:
        backbone = keras.applications.MobileNetV3Small(
            input_shape=(size, size, 3),
            include_top=False,
            weights="imagenet",
            pooling="avg",
            include_preprocessing=True,
            minimalistic=variant is Backbone.MOBILENET_V3_SMALL_MINIMALISTIC,
        )
        backbone_inputs = inputs
    # training=False keeps BatchNorm statistics frozen even while fine-tuning; updating them
    # on small batches of a small dataset degrades the pretrained features.
    features = backbone(backbone_inputs, training=False)
    features = keras.layers.Dropout(dropout)(features)
    logits = keras.layers.Dense(class_count, name="species")(features)
    return keras.Model(inputs, logits, name="sorghum_image_model"), backbone


def load_images(records: list[ImageRecord], data_root: Path) -> np.ndarray:
    """Loads records as an (n, size, size, 3) uint8 array, using the shared preprocessing."""
    return np.stack(
        [load_model_input(data_root / r.image_path, MODEL_INPUT_SIZE_PX) for r in records]
    )


def class_indices(records: list[ImageRecord]) -> np.ndarray:
    """Head output index of each record's class."""
    return np.array([SPECIES_CLASS_NAMES.index(r.class_name) for r in records], dtype=np.int64)


def _records_in(records: list[ImageRecord], splits: dict[str, Split], split: Split) -> list[ImageRecord]:
    return [r for r in records if splits[r.sha256] is split]


def _layers_before(backbone: keras.Model, first_fine_tuned_layer: str | None) -> list:
    """The backbone layers that stay frozen in the fine-tune phase. Looked up before training
    starts, so a wrong layer name fails in seconds and not after the head phase."""
    if first_fine_tuned_layer is None:
        return []
    names = [layer.name for layer in backbone.layers]
    if first_fine_tuned_layer not in names:
        raise ValueError(
            f"{backbone.name} has no layer {first_fine_tuned_layer!r} "
            "(TrainingSettings.first_fine_tuned_layer)"
        )
    return backbone.layers[: names.index(first_fine_tuned_layer)]


def _restore_with_optimizer(model: keras.Model, weights_path: Path) -> None:
    """Loads weights and optimizer state saved after an epoch of the same phase."""
    # The optimizer's variables must exist before its saved state can be loaded into them.
    model.optimizer.build(model.trainable_variables)
    model.load_weights(weights_path)


def make_dataset(
    paths: list[Path],
    labels: np.ndarray,
    sha256s: list[str],
    batch_size: int,
    cache_dir: Path,
    cache_name: str,
    is_training: bool,
) -> tf.data.Dataset:
    """Batches of (0-255 float pixels, class index), decoded once into a tf.data file cache.

    `sha256s` name the photos (in order) for the cache name. Training batches are shuffled
    and augmented after the cache, so every epoch sees new augmentations.
    """
    path_strings = [str(path) for path in paths]

    def load(path: tf.Tensor, label: tf.Tensor) -> tuple[tf.Tensor, tf.Tensor]:
        image = tf.numpy_function(
            lambda p: load_model_input(Path(p.decode()), MODEL_INPUT_SIZE_PX), [path], tf.uint8
        )
        image.set_shape((MODEL_INPUT_SIZE_PX, MODEL_INPUT_SIZE_PX, 3))
        return image, label

    cache_dir.mkdir(parents=True, exist_ok=True)
    dataset = (
        tf.data.Dataset.from_tensor_slices((path_strings, labels))
        .map(load, num_parallel_calls=tf.data.AUTOTUNE)
        .cache(str(_input_cache_prefix(cache_dir, cache_name, sha256s)))
    )
    if is_training:
        dataset = dataset.shuffle(SHUFFLE_BUFFER_IMAGES, seed=SHUFFLE_SEED, reshuffle_each_iteration=True)
    dataset = dataset.map(lambda x, y: (tf.cast(x, tf.float32), y)).batch(batch_size)
    if is_training:
        # After the cache, so every epoch sees new augmentations of the same decoded photos.
        augment = _augmentation()
        dataset = dataset.map(lambda x, y: (augment(x, training=True), y))
    return dataset.prefetch(tf.data.AUTOTUNE)


def _input_cache_prefix(cache_dir: Path, name: str, sha256s: list[str]) -> Path:
    """Names the cache after the photos (in order), the input size and the preprocessing code.

    tf.data reads whatever cache file has the given name, so a cache built from other photos or
    an older preprocessing would silently train on the wrong pixels; a new name rebuilds it.
    """
    digest = hashlib.sha256()
    digest.update(str(MODEL_INPUT_SIZE_PX).encode())
    digest.update(inspect.getsource(preprocessing).encode())
    for sha256 in sha256s:
        digest.update(sha256.encode())
    return cache_dir / f"{name}-{digest.hexdigest()[:16]}"


def remove_stale_cache_locks(cache_dir: Path) -> None:
    """Deletes lock files left by a killed run. tf.data refuses to write a cache while its
    lock file exists, and only one training job runs per run directory."""
    if cache_dir.exists():
        for lock in cache_dir.glob("*.lockfile"):
            lock.unlink()


def _augmentation() -> keras.Sequential:
    """Phone-photo variation the gate must tolerate: framing, rotation, light and exposure.

    Kept modest because colour (glume, grain) is a real cue between species. Values are
    initial guesses.
    """
    return keras.Sequential(
        [
            keras.layers.RandomFlip("horizontal"),
            keras.layers.RandomRotation(0.05),
            keras.layers.RandomZoom((-0.2, 0.0)),
            keras.layers.RandomBrightness(0.15, value_range=(0, 255)),
            keras.layers.RandomContrast(0.15),
        ],
        name="augmentation",
    )


def _balanced_class_weights(records: list[ImageRecord]) -> dict[int, float]:
    """Weights each class by n / (classes * count), so small classes (millets) are not ignored."""
    counts = Counter(r.class_name for r in records)
    total = sum(counts.values())
    return {
        SPECIES_CLASS_NAMES.index(name): total / (len(SPECIES_CLASS_NAMES) * counts[name])
        for name in SPECIES_CLASS_NAMES
    }


def _compile(model: keras.Model, learning_rate: float) -> None:
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate),
        loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )


def _write_training_report(path, counts, settings, history_rows) -> None:
    head_history, fine_tune_history = history_by_phase(history_rows, settings.head_epochs)
    report = {
        "settings": settings.__dict__,
        "tensorflowVersion": tf.__version__,
        "photosPerClassAndSplit": {
            f"{name}/{split.value}": count for (name, split), count in sorted(
                counts.items(), key=lambda item: (item[0][0], item[0][1].value)
            )
        },
        "headHistory": head_history,
        "fineTuneHistory": fine_tune_history,
    }
    path.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
