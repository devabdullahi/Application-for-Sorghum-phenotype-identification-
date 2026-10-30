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
class RaceCrosswalkSettings:
    """How `race-crosswalk` looks accessions up on GRIN-Global's public search and detail pages.

    Attributes:
        seconds_between_requests: pace of uncached page fetches. Two seconds: the image download
            is finished, so this command is GRIN's only client from this team, and a search page
            answers in one to three seconds. Initial guess; slow down if GRIN answers 5xx.
        max_candidates_per_search: how many sorghum hits of one search are opened to look for
            the number. GRIN's search is fuzzy, but an accession that lists the number ranks in
            its first rows; ten keeps a rare second listing visible (ambiguous) at a bounded cost.
        page_timeout_seconds: socket read timeout per page; a detail page is about 200 kB.
    """

    seconds_between_requests: float = 2.0
    max_candidates_per_search: int = 10
    page_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.seconds_between_requests < 1:
            raise ValueError("seconds_between_requests must be at least 1 (GRIN asks for polite clients)")
        if not 1 <= self.max_candidates_per_search <= 50:
            raise ValueError("max_candidates_per_search must be in [1, 50]")
        if not 30 <= self.page_timeout_seconds <= 600:
            raise ValueError("page_timeout_seconds must be in [30, 600]")


@dataclass(frozen=True)
class CoreShortlistSettings:
    """How many accessions `core-shortlist` proposes per basic race, and the seed to request.

    Attributes:
        development_per_race, test_per_race: the type-eval-v1 planning target (protocol 5.1):
            100 accessions to train, validate and tune on, and 50 for the sealed test. At 50 per
            race a per-race accuracy near 0.9 has a Wilson 95% interval of about +-0.09.
        alternates_per_race: ranked spares for seed that fails to arrive or germinate. 30 (20%
            of the core) is an initial guess; raise it once germination rates are known.
        max_origin_share: the most of a race's core one origin country may take while other
            origins still have candidates. 0.4 is an initial guess that keeps at least three
            countries in every core and still lets Durra lean on Ethiopia and Sudan.
        seeds_per_request: placeholder quantity per accession, GRIN's usual 100-seed packet. It
            is enough to grow the plants for the panicle and glume views (protocol 7) and to
            photograph grain. Replace with the genebank's own quantity when it answers.
    """

    development_per_race: int = 100
    test_per_race: int = 50
    alternates_per_race: int = 30
    max_origin_share: float = 0.4
    seeds_per_request: int = 100

    def __post_init__(self) -> None:
        if self.development_per_race < 1 or self.test_per_race < 1:
            raise ValueError("development_per_race and test_per_race must be at least 1")
        if self.alternates_per_race < 0:
            raise ValueError("alternates_per_race must not be negative")
        if not 0 < self.max_origin_share <= 1:
            raise ValueError("max_origin_share must be in (0, 1]")
        if not 1 <= self.seeds_per_request <= 10_000:
            raise ValueError("seeds_per_request must be in [1, 10000]")

    @property
    def core_accessions_per_race(self) -> int:
        return self.development_per_race + self.test_per_race


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


@dataclass(frozen=True)
class RaceRuleSearchSettings:
    """How `race_evaluation.choose_answer_rule` searches for the answer rule on validation.

    Attributes:
        coverage_margin: the chosen rule must reach the target coverage plus this on
            validation. Coverage on about 1,000 test photos varies by roughly +-0.013 (one
            standard deviation at 80%) from validation's, so a rule chosen at exactly 0.80
            would miss the 80% target on test about half the time. 0.02 is an initial guess.
        min_group_mass, max_group_mass, group_mass_step: the grid of
            `RaceEvaluationSettings.group_probability_mass` values tried. The range is the
            setting's own valid range; steps of 0.01 move coverage by well under a point.
        max_group_sizes: `RaceEvaluationSettings.max_group_size` values tried. At most 3: a
            basic race with its two closest intermediates is still a useful answer, more
            names a large part of the fifteen races (ADR-0011).
    """

    coverage_margin: float = 0.02
    min_group_mass: float = 0.5
    max_group_mass: float = 0.99
    group_mass_step: float = 0.01
    max_group_sizes: tuple[int, ...] = (1, 2, 3)

    def __post_init__(self) -> None:
        if not 0 <= self.coverage_margin < 0.1:
            raise ValueError("coverage_margin must be in [0, 0.1)")
        if not 0.5 <= self.min_group_mass <= self.max_group_mass < 1:
            raise ValueError("need 0.5 <= min_group_mass <= max_group_mass < 1")
        if not 0 < self.group_mass_step <= 0.1:
            raise ValueError("group_mass_step must be in (0, 0.1]")
        if not self.max_group_sizes or not all(1 <= size <= 3 for size in self.max_group_sizes):
            raise ValueError("max_group_sizes must be a non-empty choice from 1, 2 and 3")

    def group_masses(self) -> list[float]:
        """The grid of group masses, rounded so 0.5 + 0.01 * k does not drift."""
        count = int(round((self.max_group_mass - self.min_group_mass) / self.group_mass_step)) + 1
        return [round(self.min_group_mass + index * self.group_mass_step, 6) for index in range(count)]


@dataclass(frozen=True)
class RaceTrainingSettings:
    """Training schedule for the race head (T9, #32) on the traits-v2 MobileNetV2 backbone.

    Same two phases as `TrainingSettings` (`train.fit_in_two_phases`): the new head first, on
    the frozen backbone, then fine-tuning from `first_fine_tuned_layer` on with BatchNorm
    statistics frozen. Same augmentation and the same uint8 224 px input as the species head.
    Validation numbers behind the defaults are in model/README.md ("Race model results").

    Attributes:
        batch_size: as `TrainingSettings.batch_size`.
        head_epochs: frozen-backbone epochs. Ten passes at Adam 1e-3 bring a linear head close
            to the best validation loss a head on cached frozen features reached. Initial guess.
        fine_tune_epochs: the best epoch by validation loss (over both phases) is kept.
            Fine-tuning at 1e-4 with balanced weights overfitted from its first epoch
            (2026-10-30, validation loss best at epoch 6 of 20), so it is short. Initial guess.
        head_learning_rate: as `TrainingSettings.head_learning_rate`.
        fine_tune_learning_rate: 3e-5, a third of the species rate, because 1e-4 overfitted
            the 4,665 training photos within one epoch. Initial guess.
        dropout: as `TrainingSettings.dropout`.
        first_fine_tuned_layer: as `TrainingSettings.first_fine_tuned_layer`; block_12 on
            keeps the layers INT8 already handles well (ADR-0010) and is the T9 plan.
        balanced_class_weights: weight races by n / (races * count) in the loss. Off: the gate
            scores every photo alike, and on validation a balanced head ranked the common
            races too low (frozen traits-v2 features, 2026-10-30: top-1 0.442 balanced against
            0.557 unweighted; selective accuracy at ~82% coverage 0.735 against 0.773). Rare
            races' recall is reported per race either way.
        min_train_photos_per_race: training refuses a race with fewer training photos. The
            smallest race, Kafir-bicolor, has 31 (30 accessions); below 20 a race's head row is
            fitted to a handful of accessions. Initial guess.
        min_evaluation_photos_per_race: per validation and test split. Kafir-bicolor has 8
            and 7; a race with fewer than 5 gives a recall that one photo moves by 20 points,
            so it is refused rather than reported. Initial guess.
    """

    batch_size: int = 32
    head_epochs: int = 10
    fine_tune_epochs: int = 10
    head_learning_rate: float = 1e-3
    fine_tune_learning_rate: float = 3e-5
    dropout: float = 0.2
    first_fine_tuned_layer: str | None = "block_12_expand"
    balanced_class_weights: bool = False
    min_train_photos_per_race: int = 20
    min_evaluation_photos_per_race: int = 5

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if self.head_epochs < 1 or self.fine_tune_epochs < 0:
            raise ValueError("head_epochs must be >= 1 and fine_tune_epochs >= 0")
        if not 0 < self.fine_tune_learning_rate <= self.head_learning_rate < 1:
            raise ValueError("need 0 < fine_tune_learning_rate <= head_learning_rate < 1")
        if not 0 <= self.dropout < 1:
            raise ValueError("dropout must be in [0, 1)")
        if self.first_fine_tuned_layer == "":
            raise ValueError("first_fine_tuned_layer must be a layer name or None")
        if self.min_train_photos_per_race < 1 or self.min_evaluation_photos_per_race < 1:
            raise ValueError("minimum photos per race must be at least 1")


@dataclass(frozen=True)
class RaceGateSettings:
    """The T9 (#32) acceptance gate for the race model, checked on the untouched test split.

    Attributes:
        min_selective_accuracy: group-aware accuracy over answered photos (true race in the
            returned group). 0.89 is the product target (ADR-0011).
        min_coverage: the share of test photos that must get an answer at that accuracy. 89%
            on a fraction of the photos is not 89% (ADR-0011); 0.80 is the team's bar (#32).
        min_points_over_baseline: the selective accuracy must beat the better of the majority
            and planting baselines by this much, so the model is not just recognising the
            commonest race or the planting's board and light. 0.10 is the team's bar (#32).
        max_int8_accuracy_delta: largest allowed |float - INT8| selective accuracy under the
            same rule and test protocol; the phones run INT8. Same bar as the species head
            (`ExportSettings.max_quantization_accuracy_delta`).
    """

    min_selective_accuracy: float = 0.89
    min_coverage: float = 0.80
    min_points_over_baseline: float = 0.10
    max_int8_accuracy_delta: float = 0.02

    def __post_init__(self) -> None:
        if not 0 < self.min_selective_accuracy <= 1 or not 0 < self.min_coverage <= 1:
            raise ValueError("min_selective_accuracy and min_coverage must be in (0, 1]")
        if not 0 <= self.min_points_over_baseline < 1:
            raise ValueError("min_points_over_baseline must be in [0, 1)")
        if not 0 <= self.max_int8_accuracy_delta < 0.5:
            raise ValueError("max_int8_accuracy_delta must be in [0, 0.5)")


@dataclass(frozen=True)
class TraitLabelSettings:
    """Which GRIN-labelled states a learned trait head outputs (T12, #35; `cultivar_traits`).

    Attributes:
        min_train_accessions_per_state: a state gets a head output only with at least this
            many training accessions. Below it the output row is fitted to a handful of
            accessions and its probability is noise; `shared/` gives such states the noise
            floor instead. 20 is the race head's minimum (`RaceTrainingSettings`). It drops
            grain colour 6 "Other" (14) and panicle 12 "Broom corn" (18). Initial guess.
    """

    min_train_accessions_per_state: int = 20

    def __post_init__(self) -> None:
        if self.min_train_accessions_per_state < 1:
            raise ValueError("min_train_accessions_per_state must be at least 1")


@dataclass(frozen=True)
class TraitGateSettings:
    """The R6 gate a learned trait head must pass on the untouched test split (ARCHITECTURE.md
    risk R6: learned traits are added one at a time, each gated by held-out accuracy).

    Set on 2026-10-30 before any trait head was scored, so the gate was not tuned to results.
    Measured on the INT8 model with its validation-fitted temperature, the outputs the phones see.

    Attributes:
        min_accuracy: top-1 accuracy over the test photos with a state the head outputs. Naive
            Bayes weighs each trait by its calibrated probabilities, so a weaker head is not
            wrong, but a trait shown to the user for correction should be right most of the
            time: 0.70 is an initial guess (team bar, ASSUMPTION - confirm).
        min_points_over_baseline: accuracy must beat the better of the majority-state and
            planting baselines by this much, so the head reads the trait rather than the
            commonest state or the planting's board and light. 0.10, as the race gate.
        min_macro_recall: mean per-state recall. A head can reach high accuracy on a trait
            dominated by one state while never naming the others; 0.50 asks that it names the
            average state at least half the time. Initial guess.
        max_ece: expected calibration error after temperature scaling. Naive Bayes needs
            honest probabilities (risk R4); 0.05 is about the race model's (0.050) and
            well above the species head's (0.013). Initial guess.
        max_int8_accuracy_delta: largest allowed |float - INT8| accuracy on test; the phones
            run INT8. Same bar as `ExportSettings.max_quantization_accuracy_delta`.
    """

    min_accuracy: float = 0.70
    min_points_over_baseline: float = 0.10
    min_macro_recall: float = 0.50
    max_ece: float = 0.05
    max_int8_accuracy_delta: float = 0.02

    def __post_init__(self) -> None:
        if not 0 < self.min_accuracy <= 1 or not 0 < self.min_macro_recall <= 1:
            raise ValueError("min_accuracy and min_macro_recall must be in (0, 1]")
        if not 0 <= self.min_points_over_baseline < 1:
            raise ValueError("min_points_over_baseline must be in [0, 1)")
        if not 0 < self.max_ece < 1:
            raise ValueError("max_ece must be in (0, 1)")
        if not 0 <= self.max_int8_accuracy_delta < 0.5:
            raise ValueError("max_int8_accuracy_delta must be in [0, 0.5)")


@dataclass(frozen=True)
class TraitTrainingSettings:
    """Training schedule for the learned trait heads (T12, #35) on the traits-v2 backbone.

    Same two phases as the race head (`train.fit_in_two_phases`). The defaults keep the
    backbone frozen (`fine_tune_epochs = 0`), so the heads can sit next to the traits-v2
    species head in one model without changing its outputs (ADR-0006). Fine-tuning is kept
    only if it beats the frozen heads on validation (model/README.md, "Trait heads").

    Attributes:
        batch_size: as `RaceTrainingSettings.batch_size`.
        head_epochs: frozen-backbone epochs; the best validation loss is kept. Initial guess.
        fine_tune_epochs: 0 keeps the traits-v2 backbone; see above.
        head_learning_rate: as `RaceTrainingSettings.head_learning_rate`.
        fine_tune_learning_rate: 3e-5, the rate that did not overfit the race head; 1e-4 did.
        dropout: as `RaceTrainingSettings.dropout`.
        first_fine_tuned_layer: as `RaceTrainingSettings.first_fine_tuned_layer`.
    """

    batch_size: int = 32
    head_epochs: int = 15
    fine_tune_epochs: int = 0
    head_learning_rate: float = 1e-3
    fine_tune_learning_rate: float = 3e-5
    dropout: float = 0.2
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
        if self.first_fine_tuned_layer == "":
            raise ValueError("first_fine_tuned_layer must be a layer name or None")


@dataclass(frozen=True)
class SpeciesDecisionSettings:
    """The app's "not sorghum" / "unsure" / "no plant" thresholds, for offline evaluation.

    A copy of `SpeciesSettings` in `shared/.../species/SpeciesGate.kt`: the defaults must equal
    the Kotlin defaults, so an evaluation here scores the decision the phone would show. The
    sorghum threshold and the temperature are not here; they come from `traits-vN.json`.

    Attributes:
        min_not_sorghum_probability: 1 - P(sorghum) needed before saying "not sorghum".
        min_named_look_alike_probability: top look-alike probability needed to name it.
        min_no_plant_probability: `no_plant` probability needed to say "no plant".
    """

    min_not_sorghum_probability: float = 0.7
    min_named_look_alike_probability: float = 0.6
    min_no_plant_probability: float = 0.6

    def __post_init__(self) -> None:
        for name in ("min_not_sorghum_probability", "min_named_look_alike_probability", "min_no_plant_probability"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class MfwdEvaluationSettings:
    """How single-plant crops are cut from MFWD trays (Genze et al. 2024) and grouped by age.

    MFWD is an external check of the species gate only; none of its photos is ever trained on.

    Attributes:
        crop_margin_fraction: margin added on each side of the plant's box, as a fraction of the
            box's long side, before squaring. 0.1 keeps leaf tips that the box clips and adds a
            little soil, like an app photo framed on one plant. Not tuned.
        min_box_side_px: a box whose long side (in the 2456 x 2058 tray image) is below this is
            skipped. MFWD boxes start at about 20 px, i.e. a cotyledon that becomes a blur of
            green after upscaling to 224 px; no one could tell sorghum from it. 64 px is the
            smallest box with several leaf-widths of detail. Applied to every species, so the
            comparison between them stays fair. Initial guess; results by box size are reported.
        stage_bin_days: width of the growth-stage bins in days since the tray's first
            annotated image (MFWD publishes no sowing date). 7 gives weekly bins.
    """

    crop_margin_fraction: float = 0.1
    min_box_side_px: int = 64
    stage_bin_days: int = 7

    def __post_init__(self) -> None:
        if not 0 <= self.crop_margin_fraction <= 1:
            raise ValueError("crop_margin_fraction must be in [0, 1]")
        if not 8 <= self.min_box_side_px <= 1024:
            raise ValueError("min_box_side_px must be in [8, 1024]")
        if not 1 <= self.stage_bin_days <= 60:
            raise ValueError("stage_bin_days must be in [1, 60]")
