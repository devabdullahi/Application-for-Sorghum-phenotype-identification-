import json

import pytest

from sorghum_model.metadata import (
    InputQuantization,
    build_metadata,
    model_file_names,
    validate_metadata,
    write_metadata,
)
from sorghum_model.species_classes import SPECIES_CLASS_NAMES


def _metadata(**overrides):
    arguments = {
        "version": 1,
        "created_on": "2026-10-21",
        "input_size_px": 224,
        "input_quantization": InputQuantization(scale=1.0, zero_point=0),
        "species_output_index": 0,
        "temperature": 1.4,
        "sorghum_threshold": 0.8,
        "evaluation": {},
        "quantization_parity": {},
        "training_data": {},
        "ship_bar": {"problems": []},
        "below_bar": False,
    }
    arguments.update(overrides)
    return build_metadata(**arguments)


def test_model_and_metadata_share_version():
    assert model_file_names(3) == ("traits-v3.tflite", "traits-v3.json")


def test_species_classes_follow_head_order():
    classes = _metadata()["heads"]["species"]["classes"]
    assert [c["id"] for c in classes] == list(SPECIES_CLASS_NAMES)
    assert classes[0] == {"id": "sorghum_bicolor", "group": "sorghum"}


@pytest.mark.parametrize("field, value", [("temperature", 0.0), ("sorghum_threshold", 1.0)])
def test_rejects_out_of_range_calibration(field, value):
    with pytest.raises(ValueError):
        _metadata(**{field: value})


def test_rejects_mismatched_model_file():
    metadata = _metadata()
    metadata["modelFile"] = "traits-v2.tflite"
    with pytest.raises(ValueError, match="modelFile"):
        validate_metadata(metadata)


def test_written_file_is_valid_json(tmp_path):
    path = tmp_path / "traits-v1.json"
    write_metadata(_metadata(), path)
    assert json.loads(path.read_text())["modelVersion"] == 1


def test_licence_summary_is_additive_under_training_data():
    # The app reads schemaVersion, input and heads.species; trainingData may only grow.
    metadata = _metadata(training_data={"licenses": ["cc-by", "cc-by-nc"], "nonCommercial": True})
    assert metadata["schemaVersion"] == 1
    assert set(metadata["input"]) >= {"widthPx", "heightPx", "quantization", "resize"}
    assert set(metadata["heads"]["species"]) >= {
        "outputIndex", "classes", "temperature", "sorghumThreshold"
    }
    assert metadata["trainingData"]["nonCommercial"] is True
