import pytest

from sorghum_model.settings import (
    ExportSettings,
    GrinDescriptorSettings,
    PublicDatasetSettings,
    RaceTrainingSettings,
    SplitSettings,
    TrainingSettings,
)


def test_defaults_are_valid():
    SplitSettings(), TrainingSettings(), ExportSettings(), PublicDatasetSettings(), GrinDescriptorSettings()


@pytest.mark.parametrize(
    "build",
    [
        lambda: SplitSettings(validation_fraction=0.5),
        lambda: SplitSettings(salt=""),
        lambda: TrainingSettings(fine_tune_learning_rate=1e-2, head_learning_rate=1e-3),
        lambda: TrainingSettings(dropout=1.0),
        lambda: ExportSettings(min_sorghum_precision=1.0),
        lambda: ExportSettings(converter_tensorflow_version="2.17.1"),
        lambda: ExportSettings(converter_tensorflow_version="latest"),
        lambda: TrainingSettings(first_fine_tuned_layer=""),
        lambda: ExportSettings(ece_bins=1),
        lambda: PublicDatasetSettings(images_per_sequence_group=0),
        lambda: PublicDatasetSettings(grain_images_per_class=0),
        lambda: GrinDescriptorSettings(seconds_between_requests=0.5),
        lambda: GrinDescriptorSettings(study_page_timeout_seconds=59),
        lambda: GrinDescriptorSettings(study_page_timeout_seconds=3601),
    ],
)
def test_rejects_out_of_range_values(build):
    with pytest.raises(ValueError):
        build()


def test_backbone_defaults_to_the_one_that_quantizes_closely():
    from sorghum_model.settings import Backbone, TrainingSettings

    assert TrainingSettings().backbone is Backbone.MOBILENET_V2
    assert TrainingSettings(first_fine_tuned_layer=None).first_fine_tuned_layer is None
    # A training report stores the value; reading it back gives the enum.
    assert TrainingSettings(backbone="MobileNetV3-Small").backbone is Backbone.MOBILENET_V3_SMALL


def test_rejects_an_unknown_backbone():
    import pytest

    from sorghum_model.settings import TrainingSettings

    with pytest.raises(ValueError):
        TrainingSettings(backbone="ResNet50")


def test_lab_datasets_skip_the_near_duplicate_pass():
    # Their close-ups hash alike and chain into false groups (SplitSettings docstring).
    assert set(SplitSettings().near_duplicate_exempt_sources) == {
        "grainset-sorghum",
        "grainset-maize",
        "sorghum-disease-2024",
    }


@pytest.mark.parametrize(
    "fields",
    [
        {"batch_size": 0},
        {"head_epochs": 0},
        {"fine_tune_epochs": -1},
        {"fine_tune_learning_rate": 2e-3},
        {"head_learning_rate": 1.0},
        {"dropout": 1.0},
        {"first_fine_tuned_layer": ""},
        {"min_train_photos_per_race": 0},
        {"min_evaluation_photos_per_race": 0},
    ],
)
def test_race_training_settings_refuse_values_outside_their_range(fields):
    with pytest.raises(ValueError):
        RaceTrainingSettings(**fields)


def test_race_training_settings_accept_their_range_edges():
    RaceTrainingSettings(
        batch_size=1, head_epochs=1, fine_tune_epochs=0, fine_tune_learning_rate=1e-3, dropout=0.0,
        first_fine_tuned_layer=None, min_train_photos_per_race=1, min_evaluation_photos_per_race=1,
    )
