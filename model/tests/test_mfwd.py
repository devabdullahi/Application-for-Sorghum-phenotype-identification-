"""MFWD external check: ground truth, crops, the app's decision rule and the scoring."""

import math
from datetime import datetime

import pytest

from sorghum_model.mfwd import (
    CropPrediction,
    EppoGroup,
    PlantBox,
    SpeciesDecision,
    SpeciesOutcome,
    box_size_bin,
    boxes_to_score,
    capture_time,
    days_since_tray_start,
    decide_species,
    photo_key,
    eppo_group,
    evaluation_report,
    plant_calls,
    read_ground_truth,
    read_predictions,
    sorghum_vs_not,
    square_crop_box,
    stage_bin,
    write_predictions,
)
from sorghum_model.settings import MfwdEvaluationSettings, SpeciesDecisionSettings
from sorghum_model.species_classes import SpeciesGroup

SETTINGS = MfwdEvaluationSettings()
DECISION = SpeciesDecisionSettings()
CLASS_IDS = ("sorghum_bicolor", "maize", "other_grass", "no_plant")
CLASS_GROUPS = (SpeciesGroup.SORGHUM, SpeciesGroup.LOOK_ALIKE, SpeciesGroup.OTHER_PLANT, SpeciesGroup.NO_PLANT)
THRESHOLD = 0.2


def box(x_min=100, y_min=100, x_max=200, y_max=150, *, code="SORFR", track=1, tray=121806,
        image="SORVU/121806/SORFR_121806_2021Y10M07D_18H57M39S_img", bbox=1) -> PlantBox:
    return PlantBox(track, code, bbox, x_min, y_min, x_max, y_max, image, tray)


def test_eppo_groups_merge_varieties_and_skip_unidentified_weeds():
    assert eppo_group("SORFR") == eppo_group("SORVU") == EppoGroup.SORGHUM
    assert eppo_group("ZEAKJ") == eppo_group("ZEALP") == EppoGroup.MAIZE
    assert {eppo_group(c) for c in ("ECHCG", "AGRRE", "ALOMY", "POAAN")} == {EppoGroup.GRASS_WEED}
    assert eppo_group("CHEAL") == EppoGroup.BROADLEAF_WEED
    assert eppo_group("Weed") is None


def test_ground_truth_is_read_and_empty_boxes_are_refused(tmp_path):
    header = "track_id,label_id,bbox_id,xmin,ymin,xmax,ymax,filename,tray_id\n"
    path = tmp_path / "gt.csv"
    path.write_text(header + "5,ECHCG,9,10,20,40,80,ECHCG/1/ECHCG_1_2021Y07M28D_00H49M09S_img,1\n")
    [read] = read_ground_truth(path)
    assert (read.eppo_code, read.long_side_px, read.image_stem) == (
        "ECHCG", 60, "ECHCG_1_2021Y07M28D_00H49M09S_img"
    )
    path.write_text(header + "5,ECHCG,9,10,20,10,80,ECHCG/1/x,1\n")
    with pytest.raises(ValueError, match="empty box"):
        read_ground_truth(path)


def test_capture_time_and_days_since_the_trays_first_photo():
    assert capture_time("SORFR_121806_2021Y10M07D_18H57M39S_img") == datetime(2021, 10, 7, 18, 57, 39)
    with pytest.raises(ValueError):
        capture_time("no_time_here")
    first = box(image="S/1/A_1_2021Y10M07D_12H00M00S_img", tray=1)
    later = box(image="S/1/A_1_2021Y10M10D_00H00M00S_img", tray=1)
    other_tray = box(image="S/2/A_2_2021Y11M01D_00H00M00S_img", tray=2)
    days = days_since_tray_start([later, first, other_tray])
    assert days[first.image_name] == 0
    assert days[later.image_name] == pytest.approx(2.5)
    assert days[other_tray.image_name] == 0


def test_photo_key_ignores_the_variety_or_folder_code():
    assert photo_key("ZEALP_127801_2021Y08M03D_08H00M29S_img") == photo_key(
        "ZEAMX_127801_2021Y08M03D_08H00M29S_img"
    )
    with pytest.raises(ValueError):
        photo_key("nounderscore")


def test_crop_is_a_centred_square_with_margin():
    # Long side 100, margin 0.1 each side: 120 px square centred on (150, 125).
    assert square_crop_box(box(), 2456, 2058, 0.1) == (90, 65, 210, 185)


def test_crop_is_shifted_inside_the_image_not_shrunk():
    assert square_crop_box(box(0, 0, 100, 50), 2456, 2058, 0.1) == (0, 0, 120, 120)
    assert square_crop_box(box(2400, 2000, 2456, 2058), 2456, 2058, 0.1) == (2386, 1988, 2456, 2058)


def test_crop_larger_than_the_image_is_cut_to_the_short_side():
    # Still centred on the box's centre x = 1200: 1200 - 2058 / 2 = 171.
    assert square_crop_box(box(0, 0, 2400, 2000), 2456, 2058, 0.1) == (171, 0, 2229, 2058)


def test_box_size_rule_at_just_below_and_above_the_minimum():
    side = SETTINGS.min_box_side_px
    boxes = [box(0, 0, side - 1, 10, bbox=1), box(0, 0, side, 10, bbox=2), box(0, 0, side + 1, 10, bbox=3),
             box(0, 0, 500, 10, code="Weed", bbox=4)]
    assert [b.bbox_id for b in boxes_to_score(boxes, SETTINGS)] == [2, 3]


def test_sorghum_is_decided_at_the_threshold_and_not_just_below():
    at = decide_species([THRESHOLD, 0.8 - THRESHOLD, 0.2, 0.0], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    below = decide_species([THRESHOLD - 0.001, 0.8, 0.201, 0.0], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    assert at.outcome == SpeciesOutcome.SORGHUM
    assert below.outcome == SpeciesOutcome.NOT_SORGHUM


def test_not_sorghum_needs_confidence_and_names_only_a_confident_look_alike():
    named = decide_species([0.1, 0.65, 0.25, 0.0], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    unnamed = decide_species([0.1, 0.5, 0.4, 0.0], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    other_plant = decide_species([0.1, 0.2, 0.7, 0.0], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    assert (named.outcome, named.named_look_alike) == (SpeciesOutcome.NOT_SORGHUM, "maize")
    assert (unnamed.outcome, unnamed.named_look_alike) == (SpeciesOutcome.NOT_SORGHUM, None)
    assert (other_plant.outcome, other_plant.named_look_alike) == (SpeciesOutcome.NOT_SORGHUM, None)
    # 1 - P(sorghum) below 0.7 is unsure. Needs a threshold above P(sorghum) to get there.
    unsure = decide_species([0.35, 0.65, 0.0, 0.0], CLASS_IDS, CLASS_GROUPS, 0.4, DECISION)
    assert unsure.outcome == SpeciesOutcome.UNSURE


def test_no_plant_and_a_sorghum_top_class_below_the_threshold():
    no_plant = decide_species([0.0, 0.1, 0.2, 0.7], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    weak_no_plant = decide_species([0.0, 0.25, 0.25, 0.5], CLASS_IDS, CLASS_GROUPS, THRESHOLD, DECISION)
    top_sorghum = decide_species([0.3, 0.25, 0.25, 0.2], CLASS_IDS, CLASS_GROUPS, 0.35, DECISION)
    assert no_plant.outcome == SpeciesOutcome.NO_PLANT
    assert weak_no_plant.outcome == SpeciesOutcome.UNSURE
    assert top_sorghum.outcome == SpeciesOutcome.UNSURE


def prediction(code, track, called, days=0.0, side=100, tray=1, bbox=0) -> CropPrediction:
    outcome = SpeciesOutcome.SORGHUM if called else SpeciesOutcome.NOT_SORGHUM
    return CropPrediction(tray, track, bbox, code, "img", days, side,
                          SpeciesDecision(outcome, 0.9 if called else 0.1, "maize", 0.5, None))


def test_sorghum_vs_not_counts():
    m = sorghum_vs_not([True, True, False, False], [True, False, True, False])
    assert (m["accuracy"], m["precision"], m["recall"]) == (0.5, 0.5, 0.5)
    assert math.isnan(sorghum_vs_not([False], [False])["precision"])


def test_a_plant_is_called_sorghum_by_a_strict_majority_of_its_crops():
    rows = [prediction("SORFR", 1, True), prediction("SORFR", 1, True), prediction("SORFR", 1, False),
            prediction("ECHCG", 2, True), prediction("ECHCG", 2, False)]
    calls = plant_calls(rows)
    assert calls[1][:2] == ("SORFR", True)
    assert calls[2][:2] == ("ECHCG", False)  # half is not a majority
    with pytest.raises(ValueError, match="several species"):
        plant_calls([prediction("SORFR", 3, True), prediction("ECHCG", 3, True)])


def test_stage_and_box_size_bins():
    assert stage_bin(0.0, SETTINGS) == "0-6 d"
    assert stage_bin(6.99, SETTINGS) == "0-6 d"
    assert stage_bin(7.0, SETTINGS) == "7-13 d"
    assert box_size_bin(64, SETTINGS) == "64-127 px"
    assert box_size_bin(127, SETTINGS) == "64-127 px"
    assert box_size_bin(128, SETTINGS) == "128-255 px"
    assert box_size_bin(512, SETTINGS) == ">=512 px"


def test_report_scores_photos_plants_groups_and_stages(tmp_path):
    rows = [prediction("SORFR", 1, True, days=1), prediction("SORFR", 1, False, days=9),
            prediction("SORFR", 1, True, days=10), prediction("ZEAKJ", 2, True, days=2),
            prediction("CHEAL", 3, False, days=3)]
    path = tmp_path / "predictions.csv"
    write_predictions(rows, path)
    assert read_predictions(path) == rows

    report = evaluation_report(read_predictions(path), SETTINGS)
    assert report["perPhoto"]["photos"] == 5
    assert report["perPhoto"]["recall"] == pytest.approx(2 / 3)
    assert report["perPlant"]["photos"] == 3
    assert report["perPlant"]["precision"] == 0.5  # sorghum plant and the maize plant
    assert report["perGroup"]["maize"]["calledSorghumRate"] == 1.0
    assert report["perEppoCode"]["CHEAL"]["outcomes"]["notSorghum"] == 1.0
    assert list(report["perStage"]["sorghum"]) == ["0-6 d", "7-13 d"]
    assert report["perStage"]["sorghum"]["7-13 d"]["calledSorghumRate"] == 0.5
    # The plant is called sorghum overall (2 of 3) and at 0-6 d (1 of 1), not at 7-13 d (1 of 2).
    assert report["perStage"]["sorghum"]["0-6 d"]["plantsCalledSorghumRate"] == 1.0
    assert report["perStage"]["sorghum"]["7-13 d"]["plantsCalledSorghumRate"] == 0.0
    with pytest.raises(ValueError):
        evaluation_report([], SETTINGS)


def test_settings_are_range_checked():
    with pytest.raises(ValueError):
        MfwdEvaluationSettings(min_box_side_px=4)
    with pytest.raises(ValueError):
        SpeciesDecisionSettings(min_not_sorghum_probability=1.5)
