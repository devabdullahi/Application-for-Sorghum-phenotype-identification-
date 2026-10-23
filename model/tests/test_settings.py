import pytest

from sorghum_model.settings import (
    ExportSettings,
    PublicDatasetSettings,
    SplitSettings,
    TrainingSettings,
)


def test_defaults_are_valid():
    SplitSettings(), TrainingSettings(), ExportSettings(), PublicDatasetSettings()


@pytest.mark.parametrize(
    "build",
    [
        lambda: SplitSettings(validation_fraction=0.5),
        lambda: SplitSettings(salt=""),
        lambda: TrainingSettings(fine_tune_learning_rate=1e-2, head_learning_rate=1e-3),
        lambda: TrainingSettings(dropout=1.0),
        lambda: ExportSettings(sorghum_precision_target=1.0),
        lambda: ExportSettings(ece_bins=1),
        lambda: PublicDatasetSettings(images_per_sequence_group=0),
        lambda: PublicDatasetSettings(grain_images_per_class=0),
    ],
)
def test_rejects_out_of_range_values(build):
    with pytest.raises(ValueError):
        build()
