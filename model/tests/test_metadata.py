import json

import pytest

from sorghum_model.metadata import (
    InputQuantization,
    basic_race_head,
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
        "backbone": "MobileNetV3-Small minimalistic",
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


def _basic_race_head(**overrides):
    arguments = {
        "output_index": 1,
        "races": ["Bicolor", "Caudatum", "Durra", "Guinea", "Kafir"],
        "temperature": 1.4,
        "group_probability_mass": 0.89,
        "max_group_size": 2,
        "meets_accuracy_goal": False,
        "status": "EXPERIMENTAL",
        "evaluation": {},
        "source_model": {},
    }
    arguments.update(overrides)
    return basic_race_head(**arguments)


def test_basic_race_head_is_always_experimental():
    head = _basic_race_head()

    assert head["experimental"] is True
    assert head["meetsAccuracyGoal"] is False
    assert head["answerRule"] == {"groupProbabilityMass": 0.89, "maxGroupSize": 2}


@pytest.mark.parametrize(
    "field, value",
    [
        ("temperature", 0.0),
        ("group_probability_mass", 0.49),
        ("group_probability_mass", 1.0),
        ("max_group_size", 0),
        ("max_group_size", 6),
        ("races", ["Durra", "Durra"]),
        ("races", []),
        ("output_index", -1),
    ],
)
def test_basic_race_head_refuses_invalid_values(field, value):
    with pytest.raises(ValueError):
        _basic_race_head(**{field: value})


def test_metadata_with_a_basic_race_head_validates():
    metadata = _metadata()
    metadata["heads"]["basicRace"] = _basic_race_head()
    metadata["headOrder"] = ["species", "basicRace"]

    validate_metadata(metadata)


def test_refuses_a_basic_race_head_on_the_species_output():
    metadata = _metadata()
    metadata["heads"]["basicRace"] = _basic_race_head(output_index=0)

    with pytest.raises(ValueError, match="different outputs"):
        validate_metadata(metadata)


def test_refuses_a_head_order_that_is_not_the_output_order():
    metadata = _metadata()
    metadata["heads"]["basicRace"] = _basic_race_head()
    metadata["headOrder"] = ["basicRace", "species"]

    with pytest.raises(ValueError, match="headOrder"):
        validate_metadata(metadata)


def test_refuses_a_missed_goal_without_the_experimental_mark():
    metadata = _metadata()
    metadata["heads"]["basicRace"] = _basic_race_head()
    metadata["heads"]["basicRace"]["experimental"] = False

    with pytest.raises(ValueError, match="experimental"):
        validate_metadata(metadata)
