"""Tunable values for training and export, with the reason for each default.

Mirrors the `*Settings` data classes in `shared/`: every threshold lives here with a default
and a range check, never as a bare literal in pipeline code. Defaults marked "initial guess"
must be tuned once real data is in.
"""

from dataclasses import dataclass

# MobileNetV3-Small's ImageNet weights were trained at 224 px. Matching it keeps the
# pretrained features useful, and it is the size `shared/` resizes to before `ImageModel`.
MODEL_INPUT_SIZE_PX = 224


@dataclass(frozen=True)
class SplitSettings:
    """How groups are divided between train, validation and test.

    Attributes:
        validation_fraction: share of groups used to pick epochs, fit the temperature and pick
            the sorghum threshold. 15% is an initial guess that leaves enough groups to
            calibrate on while classes are small.
        test_fraction: share of groups held out for the final numbers only. Same reasoning.
        salt: names the split scheme. Changing it reshuffles all groups, so it changes only
            together with a new model version.
    """

    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    salt: str = "species-v1"

    def __post_init__(self) -> None:
        if not 0 < self.validation_fraction < 0.5:
            raise ValueError("validation_fraction must be in (0, 0.5)")
        if not 0 < self.test_fraction < 0.5:
            raise ValueError("test_fraction must be in (0, 0.5)")
        if not self.salt:
            raise ValueError("salt must not be empty")


@dataclass(frozen=True)
class TrainingSettings:
    """Training schedule for the species head.

    Attributes:
        batch_size: 32 fits an 8 GB laptop GPU or Apple silicon at 224 px.
        head_epochs: epochs with the backbone frozen, so the new random head does not wreck
            the pretrained features with large early gradients. Initial guess.
        fine_tune_epochs: epochs with the whole network trainable. Initial guess; the best
            epoch by validation loss is kept.
        head_learning_rate: Adam rate for the frozen phase; 1e-3 is Adam's usual default.
        fine_tune_learning_rate: 10x lower than the head rate, the usual fine-tuning choice,
            so pretrained weights move slowly.
        dropout: before the head; regularises the small classes. Initial guess.
        min_train_images_per_class: training refuses to start below this, because a class with
            a handful of photos gives a head that is confidently wrong. Initial guess.
        min_evaluation_images_per_class: per validation and test split. Below this the
            temperature, threshold and accuracy for that class are noise.
    """

    batch_size: int = 32
    head_epochs: int = 5
    fine_tune_epochs: int = 15
    head_learning_rate: float = 1e-3
    fine_tune_learning_rate: float = 1e-4
    dropout: float = 0.2
    min_train_images_per_class: int = 50
    min_evaluation_images_per_class: int = 10

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.head_epochs < 1 or self.fine_tune_epochs < 0:
            raise ValueError("head_epochs must be >= 1 and fine_tune_epochs >= 0")
        if not 0 < self.fine_tune_learning_rate <= self.head_learning_rate < 1:
            raise ValueError("need 0 < fine_tune_learning_rate <= head_learning_rate < 1")
        if not 0 <= self.dropout < 1:
            raise ValueError("dropout must be in [0, 1)")
        if self.min_train_images_per_class < 1 or self.min_evaluation_images_per_class < 1:
            raise ValueError("minimum images per class must be at least 1")


@dataclass(frozen=True)
class ExportSettings:
    """INT8 export, calibration and the species decision threshold.

    Attributes:
        representative_images: photos from the training split used to choose INT8 ranges.
            A few hundred covers the activation range; more only slows conversion.
        ece_bins: equal-width confidence bins for expected calibration error; 15 is the
            common choice in the calibration literature.
        sorghum_precision_target: the threshold on P(sorghum) is the lowest one whose
            validation precision reaches this value. A non-sorghum sample that passes the gate
            gets a confident wrong cultivar, which is worse than a retake, so precision is
            favoured over recall. Initial guess, tune on field photos.
        min_threshold_predictions: a threshold supported by fewer validation predictions than
            this is rejected as noise.
        fixture_images: test-split photos exported with expected outputs for the parity tests
            on Android and iOS.
    """

    representative_images: int = 300
    ece_bins: int = 15
    sorghum_precision_target: float = 0.97
    min_threshold_predictions: int = 20
    fixture_images: int = 12

    def __post_init__(self) -> None:
        if self.representative_images < 1:
            raise ValueError("representative_images must be at least 1")
        if self.ece_bins < 2:
            raise ValueError("ece_bins must be at least 2")
        if not 0.5 < self.sorghum_precision_target < 1:
            raise ValueError("sorghum_precision_target must be in (0.5, 1)")
        if self.min_threshold_predictions < 1 or self.fixture_images < 1:
            raise ValueError("min_threshold_predictions and fixture_images must be at least 1")
