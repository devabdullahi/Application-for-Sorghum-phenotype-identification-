import numpy as np

from conftest import make_record
from sorghum_model.label_review import REVIEW_PROMPTS, judge, review_records
from sorghum_model.manifest import LabelStatus
from sorghum_model.settings import LabelReviewSettings

SETTINGS = LabelReviewSettings(min_class_probability=0.5, max_plant_probability=0.2, batch_size=2)


def _probabilities(**per_prompt):
    """Prompt probabilities with the given values; the rest shares what is left equally."""
    values = np.zeros(len(REVIEW_PROMPTS))
    texts = [p.text for p in REVIEW_PROMPTS]
    for text, value in per_prompt.items():
        values[texts.index(text.replace("_", " "))] = value
    rest = [i for i in range(len(values)) if values[i] == 0]
    values[rest] = (1 - values.sum()) / len(rest)
    return values


def test_plant_label_verified_at_the_threshold():
    verdict = judge("maize", _probabilities(Zea_mays=0.5), SETTINGS)
    assert verdict.is_verified and verdict.top_class == "maize"


def test_plant_label_not_verified_just_below_the_threshold():
    assert not judge("maize", _probabilities(Zea_mays=0.49), SETTINGS).is_verified


def test_plant_label_not_verified_when_another_class_wins():
    assert not judge("sorghum_bicolor", _probabilities(Zea_mays=0.8), SETTINGS).is_verified


def test_class_probability_sums_its_prompts():
    # other_grass has five prompts; 0.15 each is 0.6 for the class.
    probabilities = _probabilities(
        Sorghastrum_nutans=0.15, Andropogon_gerardi=0.15, Schizachyrium_scoparium=0.15,
        Bothriochloa_ischaemum=0.15,
    )
    assert judge("other_grass", probabilities, SETTINGS).is_verified


def test_no_plant_needs_plant_probability_below_the_threshold():
    soil = np.zeros(len(REVIEW_PROMPTS))
    texts = [p.text for p in REVIEW_PROMPTS]
    soil[texts.index("bare soil")] = 0.81
    soil[texts.index("Zea mays")] = 0.19
    assert judge("no_plant", soil, SETTINGS).is_verified
    soil[texts.index("bare soil")] = 0.8
    soil[texts.index("Zea mays")] = 0.2
    assert not judge("no_plant", soil, SETTINGS).is_verified


def test_review_marks_rows_and_skips_judged_and_verified_ones(tmp_path):
    rows = [
        make_record(source="commons", source_id="1", class_name="maize", label_status="unreviewed",
                    label_source="commons category 'Zea mays'"),
        make_record(source="commons", source_id="2", class_name="maize", label_status="unreviewed",
                    label_source="commons category 'Zea mays'"),
        make_record(source="commons", source_id="3", class_name="maize", label_status="unreviewed",
                    label_source="commons; bioclip-2 disagreement, top sugarcane p=0.70"),
        make_record(source_id="4"),  # verified already
    ]
    answers = iter([[_probabilities(Zea_mays=0.9), _probabilities(Saccharum_officinarum=0.9)]])
    calls = []

    def classify(paths):
        calls.append(len(paths))
        return np.array(next(answers))

    reviewed = review_records(rows, tmp_path, classify, SETTINGS)
    assert calls == [2]
    assert reviewed[0].label_status is LabelStatus.VERIFIED
    assert reviewed[0].label_source.endswith("; bioclip-2 agreement p=0.90")
    assert reviewed[1].label_status is LabelStatus.UNREVIEWED
    assert "bioclip-2 disagreement, top sugarcane p=0.90" in reviewed[1].label_source
    assert reviewed[2:] == rows[2:]


def test_an_unreadable_image_does_not_stop_the_review(tmp_path):
    rows = [
        make_record(source="commons", source_id=str(i), image_path=f"{i}.jpg", class_name="maize",
                    label_status="unreviewed", label_source="commons")
        for i in range(2)
    ]

    def classify(paths):
        if any(p.name == "0.jpg" for p in paths):
            raise OSError("cannot identify image file")
        return np.array([_probabilities(Zea_mays=0.9)] * len(paths))

    reviewed = review_records(rows, tmp_path, classify, SETTINGS)
    assert reviewed[0] == rows[0]
    assert reviewed[1].label_status is LabelStatus.VERIFIED
