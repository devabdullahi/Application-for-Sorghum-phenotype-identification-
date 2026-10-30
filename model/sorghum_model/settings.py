"""Tunable values for training and export, with the reason for each default.

Mirrors the `*Settings` data classes in `shared/`: every threshold lives here with a default
and a range check, never as a bare literal in pipeline code. Defaults marked "initial guess"
must be tuned once real data is in.
"""

from dataclasses import dataclass
from enum import StrEnum

# The backbones' ImageNet weights were trained at 224 px. Matching it keeps the pretrained
# features useful, and it is the size `shared/` resizes to before `ImageModel`.
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
        near_duplicate_max_distance: two photos whose 64-bit dHashes differ in at most this
            many bits are treated as the same picture (`near_duplicates.py`). Resizing and
            JPEG recompression flip a few bits; different photos of one plant usually differ
            in 10 or more. Initial guess, tune by looking at the pairs it finds.
        near_duplicate_exempt_sources: sources left out of the near-duplicate pass. GrainSet
            kernels are single grains centred on the same grey belt, so their 9x8 dHashes
            barely differ: on the first real split (2026-10-23) they gave 1.1 million false
            "near-duplicate" pairs, most of them maize against sorghum, and 4,800 kernels
            were dropped as conflicting. Their copies are not published elsewhere, so only
            exact copies (sha256, `merge_manifests`) need catching there. The Sorghum Disease
            Image Dataset is exempt for the same reason (2026-10-30): its lab close-ups of
            diseased leaves and panicles chained into one near-duplicate group of 1,499
            photos (with 3 iNaturalist photos), against the dataset's blocks of 20 files,
            and that whole group fell into the test split (32% of it). Another 194 of its
            photos were dropped as "conflicting" with other classes. Both are false matches.
    """

    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    salt: str = "species-v1"
    near_duplicate_max_distance: int = 4
    near_duplicate_exempt_sources: tuple[str, ...] = (
        "grainset-sorghum",
        "grainset-maize",
        "sorghum-disease-2024",
    )

    def __post_init__(self) -> None:
        if not 0 < self.validation_fraction < 0.5:
            raise ValueError("validation_fraction must be in (0, 0.5)")
        if not 0 < self.test_fraction < 0.5:
            raise ValueError("test_fraction must be in (0, 0.5)")
        if not self.salt:
            raise ValueError("salt must not be empty")
        if not 0 <= self.near_duplicate_max_distance <= 16:
            raise ValueError("near_duplicate_max_distance must be in [0, 16]")


class Backbone(StrEnum):
    """Keras ImageNet backbones; the value is written to traits-vN.json `backbone`."""

    MOBILENET_V2 = "MobileNetV2 1.0"
    """Width 1.0. ReLU6 activations, no squeeze-and-excitation."""

    MOBILENET_V3_SMALL = "MobileNetV3-Small"
    """Hard-swish activations and squeeze-and-excitation blocks."""

    MOBILENET_V3_SMALL_MINIMALISTIC = "MobileNetV3-Small minimalistic"
    """ReLU only, no squeeze-and-excitation, 3x3 kernels: the variant Keras ships for
    quantized and edge use."""


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
        backbone: the ImageNet backbone. MobileNetV2 1.0, because the Keras MobileNetV3-Small
            weights lose about 10 accuracy points to full-integer quantization before any
            fine-tuning: with the backbone frozen and only a linear head trained on our photos
            (2026-10-29, TF 2.17 converter), MobileNetV3-Small minimalistic scored float 0.764
            and INT8 0.662 on validation, MobileNetV2 1.0 float 0.793 and INT8 0.792. The full
            MobileNetV3-Small variant was worse still (diag-1: float 0.867, INT8 0.727).
            MobileNetV2 costs about 5x the compute of MobileNetV3-Small, which an iPhone runs
            in a few milliseconds. Input size and output layout are the same for all
            backbones, so the metadata contract does not change.
        first_fine_tuned_layer: name of the first backbone layer that trains in the fine-tune
            phase; the layers before it keep their ImageNet weights, or None to fine-tune the
            whole backbone. "block_12_expand" leaves MobileNetV2's last five blocks (of 17)
            and its final 1x1 convolution trainable: the early layers hold generic edges and
            textures, and freezing them keeps their activation ranges as ImageNet left them,
            which INT8 depends on. It also makes a fine-tune step about 4x faster on this CPU
            (0.38 s against 1.55 s per batch of 32). Initial guess. The name must exist in the
            chosen backbone; training refuses otherwise.
    """

    batch_size: int = 32
    head_epochs: int = 5
    fine_tune_epochs: int = 15
    head_learning_rate: float = 1e-3
    fine_tune_learning_rate: float = 1e-4
    dropout: float = 0.2
    min_train_images_per_class: int = 50
    min_evaluation_images_per_class: int = 10
    backbone: Backbone = Backbone.MOBILENET_V2
    first_fine_tuned_layer: str | None = "block_12_expand"

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
        if self.first_fine_tuned_layer == "":
            raise ValueError("first_fine_tuned_layer must be a layer name or None")
        # Frozen dataclass: accept the enum's value (e.g. from a training report) too.
        object.__setattr__(self, "backbone", Backbone(self.backbone))


@dataclass(frozen=True)
class ExportSettings:
    """INT8 export, calibration and the species decision threshold.

    Attributes:
        representative_images: photos from the training split used to choose INT8 ranges.
            A few hundred covers the activation range; more only slows conversion.
        ece_bins: equal-width confidence bins for expected calibration error; 15 is the
            common choice in the calibration literature.
        min_sorghum_precision: the threshold on P(sorghum) is the one with the best
            validation decision accuracy among those whose validation precision reaches this
            value. A non-sorghum sample that passes the gate gets a confident wrong cultivar,
            which is worse than a retake, so precision has a floor. The floor was 0.97 until
            2026-10-29, when the threshold rule changed from "lowest threshold that reaches the
            target" to "most accurate threshold that reaches the floor": at 0.97 the gate
            stopped too many real sorghum photos for the 90% decision-accuracy bar (validation
            recall at 0.97: diag-1 0.30, v2-1 INT8 0.59). 0.95 still
            lets at most one passed photo in twenty be a non-sorghum one. Chosen on
            validation numbers only. ASSUMPTION - confirm; tune on field photos.
        min_threshold_predictions: a threshold supported by fewer validation predictions than
            this is rejected as noise.
        fixture_images: test-split photos exported with expected outputs for the parity tests
            on Android and iOS.
        min_sorghum_accuracy: ship bar. Held-out (test split) accuracy of the sorghum-vs-not
            decision the app makes with the exported threshold. The gate is the first step of
            every identification; below 90% one sample in ten is wrongly stopped or wrongly
            passed on, which the team agreed is too many to ship (review of PR #11).
        converter_tensorflow_version: ship bar. The TensorFlow major.minor version that must
            convert the model. The iPhone runtime is TensorFlowLiteSwift 2.17.0, and a model
            converted with TF 2.20 gave logits 3-12 output steps away from iOS's on the parity
            fixtures (2026-10-23), so export runs in the `export` environment (TF 2.17).
        max_quantization_accuracy_delta: ship bar. Largest allowed |float - INT8| top-1
            accuracy difference on the test split. The phones run the INT8 model, so a larger
            loss means the numbers measured on the float model do not describe the app.
            0.02 is the team's agreed bar (review of PR #11).
    """

    representative_images: int = 300
    ece_bins: int = 15
    min_sorghum_precision: float = 0.95
    min_threshold_predictions: int = 20
    fixture_images: int = 12
    min_sorghum_accuracy: float = 0.90
    max_quantization_accuracy_delta: float = 0.02
    converter_tensorflow_version: str = "2.17"

    def __post_init__(self) -> None:
        if self.representative_images < 1:
            raise ValueError("representative_images must be at least 1")
        if self.ece_bins < 2:
            raise ValueError("ece_bins must be at least 2")
        if not 0.5 < self.min_sorghum_precision < 1:
            raise ValueError("min_sorghum_precision must be in (0.5, 1)")
        if self.min_threshold_predictions < 1 or self.fixture_images < 1:
            raise ValueError("min_threshold_predictions and fixture_images must be at least 1")
        if not 0.5 < self.min_sorghum_accuracy <= 1:
            raise ValueError("min_sorghum_accuracy must be in (0.5, 1]")
        if not 0 <= self.max_quantization_accuracy_delta < 0.5:
            raise ValueError("max_quantization_accuracy_delta must be in [0, 0.5)")
        major_minor = self.converter_tensorflow_version.split(".")
        if len(major_minor) != 2 or not all(part.isdigit() for part in major_minor):
            raise ValueError("converter_tensorflow_version must look like '2.17'")


@dataclass(frozen=True)
class PublicDatasetSettings:
    """How public datasets without per-plant ids are grouped and sampled on import.

    Attributes:
        images_per_sequence_group: SorghumWeedDataset and the Sorghum Disease Image Dataset
            name files with a running number ("Rust123.jpg") and publish no plant or plot id.
            Photos taken one after another are usually of the same plant or row, so blocks of
            this many consecutive numbers form one group and land in one split. This only
            protects against leakage if the numbering follows the shooting order, which the
            datasets do not state. Initial guess.
        grain_images_per_class: GrainSet has about 100,000 sorghum and 19,000 maize kernel
            images, all on the same belt under the same light. Importing them all would make
            "isolated kernel on grey" the dominant sorghum view; this many per class is
            enough for the grain view without swamping the field photos. Initial guess.
    """

    images_per_sequence_group: int = 20
    grain_images_per_class: int = 3000

    def __post_init__(self) -> None:
        if self.images_per_sequence_group < 1:
            raise ValueError("images_per_sequence_group must be at least 1")
        if self.grain_images_per_class < 1:
            raise ValueError("grain_images_per_class must be at least 1")


@dataclass(frozen=True)
class LabelReviewSettings:
    """When BioCLIP 2 confirms an unreviewed Commons or Flickr label (`label_review.py`).

    ASSUMPTION - confirm: a zero-shot BioCLIP 2 verdict counts as verification for these rows.

    Attributes:
        min_class_probability: a plant row is verified when BioCLIP's most probable class is
            the row's class and that class has at least this probability (summed over the
            class's prompts). Above 0.5 the class beats all others together. Initial guess.
        max_plant_probability: a `no_plant` row is verified when the summed probability of
            every plant class is below this, i.e. BioCLIP sees soil, a board or a hand rather
            than a plant. Low because a plant in a no_plant photo teaches the gate to reject
            real samples. Initial guess.
        batch_size: images per forward pass; 16 fits BioCLIP 2's ViT-L/14 in 8 GB.
        checkpoint_every_rows: the manifest is saved this often, so an interrupted review
            keeps its verdicts.
    """

    min_class_probability: float = 0.5
    max_plant_probability: float = 0.2
    batch_size: int = 16
    checkpoint_every_rows: int = 200

    def __post_init__(self) -> None:
        if not 0 < self.min_class_probability < 1:
            raise ValueError("min_class_probability must be in (0, 1)")
        if not 0 < self.max_plant_probability < 1:
            raise ValueError("max_plant_probability must be in (0, 1)")
        if self.batch_size < 1 or self.checkpoint_every_rows < 1:
            raise ValueError("batch_size and checkpoint_every_rows must be at least 1")


@dataclass(frozen=True)
class DownloadSettings:
    """How download commands save progress.

    Attributes:
        checkpoint_every_photos: a class's manifest rows are saved this often during a
            download, so a crash or kill loses at most this many rows (the files stay on disk
            and are not fetched again). Writing a manifest of tens of thousands of rows takes
            well under a second, so 200 costs little against ~200 s of downloading.
    """

    checkpoint_every_photos: int = 200

    def __post_init__(self) -> None:
        if self.checkpoint_every_photos < 1:
            raise ValueError("checkpoint_every_photos must be at least 1")


@dataclass(frozen=True)
class GrinDescriptorSettings:
    """How `grin-descriptors` talks to GRIN-Global while `grin-download` uses the same server.

    Attributes:
        seconds_between_requests: this command's own pace. Six times slower than the shared
            one-per-second pace, so the image download running at the same time is not slowed.
        study_page_timeout_seconds: socket read timeout for descriptor and study pages. GRIN
            builds each page in full before sending it; the 60 s default timed out on
            2026-10-30, and SEEDWEIGHT's single study lists about 37,000 accessions in one
            page. Ten minutes is an initial guess with room for that page.
    """

    seconds_between_requests: float = 6.0
    study_page_timeout_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.seconds_between_requests < 1:
            raise ValueError("seconds_between_requests must be at least 1 (GRIN asks for polite clients)")
        if not 60 <= self.study_page_timeout_seconds <= 3600:
            raise ValueError("study_page_timeout_seconds must be in [60, 3600]")


@dataclass(frozen=True)
class RaceEvaluationSettings:
    """When the race model returns a group of races, and when it answers "unrecognized".

    The model's calibrated race probabilities are sorted; the returned group is the fewest
    top races whose probabilities add up to `group_probability_mass`. A group larger than
    `max_group_size` says too little, so the answer is "unrecognized" (an abstention, ADR-0011).
    Both values are tuned on the validation split only, never on test.

    Attributes:
        group_probability_mass: 0.9 is an initial guess: the true race should be in the group
            about nine times in ten when the probabilities are calibrated, matching the 89%
            target. Tune on validation.
        max_group_size: 3 is an initial guess: a basic race and its two closest intermediates
            (e.g. Durra, Durra-bicolor, Durra-caudatum) is still a useful answer; more is not.
            Tune on validation, reading accuracy against coverage.
    """

    group_probability_mass: float = 0.9
    max_group_size: int = 3

    def __post_init__(self) -> None:
        if not 0.5 <= self.group_probability_mass < 1:
            raise ValueError("group_probability_mass must be in [0.5, 1)")
        if not 1 <= self.max_group_size <= 15:
            raise ValueError("max_group_size must be in [1, 15] (there are fifteen races)")
