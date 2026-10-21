"""Trains the MobileNetV3-Small species head (ADR-0006). Needs the `train` extra (TensorFlow).

Two phases: first only the new head trains on a frozen ImageNet backbone, then the whole
network fine-tunes at a lower rate. The checkpoint with the lowest validation loss is kept.
"""

import json
from collections import Counter
from pathlib import Path

import keras
import numpy as np
import tensorflow as tf

from sorghum_model.manifest import ImageRecord
from sorghum_model.preprocessing import load_model_input
from sorghum_model.settings import MODEL_INPUT_SIZE_PX, TrainingSettings
from sorghum_model.species_classes import SPECIES_CLASS_NAMES
from sorghum_model.splits import Split, count_per_class_and_split, find_undersized_classes

# Fixed so two runs on the same manifests shuffle and augment the same way.
SHUFFLE_SEED = 1234

KERAS_MODEL_FILE = "species.keras"
SAVED_MODEL_DIR = "saved_model"
TRAINING_REPORT_FILE = "training_report.json"


def train_species_model(
    records: list[ImageRecord],
    splits: dict[str, Split],
    data_root: Path,
    run_dir: Path,
    settings: TrainingSettings,
) -> Path:
    """Trains, saves the best model and a SavedModel for export, and returns `run_dir`."""
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

    run_dir.mkdir(parents=True, exist_ok=True)
    keras.utils.set_random_seed(SHUFFLE_SEED)
    train_records = _records_in(records, splits, Split.TRAIN)
    validation_records = _records_in(records, splits, Split.VALIDATION)
    train_data = _make_dataset(train_records, data_root, settings.batch_size, is_training=True)
    validation_data = _make_dataset(validation_records, data_root, settings.batch_size, is_training=False)

    model, backbone = build_species_model(len(SPECIES_CLASS_NAMES), settings.dropout)
    class_weight = _balanced_class_weights(train_records)
    checkpoint_path = run_dir / KERAS_MODEL_FILE
    checkpoint = keras.callbacks.ModelCheckpoint(
        checkpoint_path, monitor="val_loss", save_best_only=True
    )

    backbone.trainable = False
    _compile(model, settings.head_learning_rate)
    head_history = model.fit(
        train_data,
        validation_data=validation_data,
        epochs=settings.head_epochs,
        class_weight=class_weight,
        callbacks=[checkpoint],
    )

    fine_tune_history = None
    if settings.fine_tune_epochs > 0:
        backbone.trainable = True
        _compile(model, settings.fine_tune_learning_rate)
        fine_tune_history = model.fit(
            train_data,
            validation_data=validation_data,
            initial_epoch=settings.head_epochs,
            epochs=settings.head_epochs + settings.fine_tune_epochs,
            class_weight=class_weight,
            callbacks=[checkpoint],
        )

    best_model = keras.models.load_model(checkpoint_path)
    best_model.export(str(run_dir / SAVED_MODEL_DIR))
    _write_training_report(
        run_dir / TRAINING_REPORT_FILE, counts, settings, head_history, fine_tune_history
    )
    return run_dir


def build_species_model(class_count: int, dropout: float) -> tuple[keras.Model, keras.Model]:
    """Returns (model, backbone). The model takes 0-255 float RGB and outputs species logits.

    `include_preprocessing=True` puts MobileNetV3's own rescaling inside the graph, so the
    device feeds raw pixel values and no normalisation constants live outside the model.
    """
    size = MODEL_INPUT_SIZE_PX
    backbone = keras.applications.MobileNetV3Small(
        input_shape=(size, size, 3),
        include_top=False,
        weights="imagenet",
        pooling="avg",
        include_preprocessing=True,
    )
    inputs = keras.Input(shape=(size, size, 3), name="image")
    # training=False keeps BatchNorm statistics frozen even while fine-tuning; updating them
    # on small batches of a small dataset degrades the pretrained features.
    features = backbone(inputs, training=False)
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


def _make_dataset(
    records: list[ImageRecord], data_root: Path, batch_size: int, is_training: bool
) -> tf.data.Dataset:
    paths = [str(data_root / r.image_path) for r in records]
    labels = class_indices(records)

    def load(path: tf.Tensor, label: tf.Tensor) -> tuple[tf.Tensor, tf.Tensor]:
        image = tf.numpy_function(
            lambda p: load_model_input(Path(p.decode()), MODEL_INPUT_SIZE_PX), [path], tf.uint8
        )
        image.set_shape((MODEL_INPUT_SIZE_PX, MODEL_INPUT_SIZE_PX, 3))
        return tf.cast(image, tf.float32), label

    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))
    if is_training:
        dataset = dataset.shuffle(len(paths), seed=SHUFFLE_SEED, reshuffle_each_iteration=True)
    dataset = dataset.map(load, num_parallel_calls=tf.data.AUTOTUNE).batch(batch_size)
    if is_training:
        augment = _augmentation()
        dataset = dataset.map(lambda x, y: (augment(x, training=True), y))
    return dataset.prefetch(tf.data.AUTOTUNE)


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


def _write_training_report(path, counts, settings, head_history, fine_tune_history) -> None:
    report = {
        "settings": settings.__dict__,
        "photosPerClassAndSplit": {
            f"{name}/{split.value}": count for (name, split), count in sorted(
                counts.items(), key=lambda item: (item[0][0], item[0][1].value)
            )
        },
        "headHistory": head_history.history,
        "fineTuneHistory": fine_tune_history.history if fine_tune_history else None,
    }
    path.write_text(json.dumps(report, indent=2, default=float) + "\n", encoding="utf-8")
