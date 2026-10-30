"""Per-accession trait labels, the reasons an accession has none, and head state selection."""

import pytest

from sorghum_model.cultivar_traits import (
    GLUME_COLOUR_TRAIT,
    PANICLE_TRAIT,
    AccessionTrait,
    TraitExclusion,
    TraitPhoto,
    head_states,
    trait_labels,
)
from sorghum_model.grin_descriptors import (
    COMBINED_PANICLE_DESCRIPTOR,
    GLUME_COLOUR,
    PANICLE_COMPACTNESS,
    PANICLE_SHAPE,
    DescriptorObservation,
    combined_panicle_state,
    ibpgr_state_for,
)
from sorghum_model.splits import Split


def glume(value: str, study: str = "S1", accession: str = "PI 1") -> DescriptorObservation:
    code, state = ibpgr_state_for(GLUME_COLOUR, value)
    return DescriptorObservation(accession, GLUME_COLOUR.code, value, code, "glumeColour", state, study, "u")


def glume_label(*values: str) -> AccessionTrait:
    observations = [glume(value, study=f"S{index}") for index, value in enumerate(values)]
    return trait_labels(GLUME_COLOUR_TRAIT, {"PI 1"}, observations)["PI 1"]


def test_agreeing_observations_give_their_state():
    label = glume_label("Purple", "Purple")
    assert label == AccessionTrait("5", None, ("Purple",))


@pytest.mark.parametrize(
    ("values", "exclusion"),
    [
        ((), TraitExclusion.NO_OBSERVATION),
        (("Tan",), TraitExclusion.NO_SINGLE_STATE),  # no IBPGR glume state
        (("Mixed", "Segregating"), TraitExclusion.NO_SINGLE_STATE),
        (("Purple", "Black"), TraitExclusion.CONFLICTING_OBSERVATIONS),
        (("Purple", "Tan"), TraitExclusion.CONFLICTING_OBSERVATIONS),  # a state and a value without one
        (("Purple", "Ochre"), TraitExclusion.UNMAPPED_VALUE),  # not in GRIN's code table
    ],
)
def test_accessions_without_one_state_are_excluded(values, exclusion):
    label = glume_label(*values)
    assert label.state == ""
    assert label.exclusion is exclusion


def test_other_descriptors_do_not_label_the_trait():
    grain = DescriptorObservation("PI 1", "KERCOLOR", "Red", "2", "grainColour", "3", "S1", "u")
    assert trait_labels(GLUME_COLOUR_TRAIT, {"PI 1"}, [grain])["PI 1"].exclusion is TraitExclusion.NO_OBSERVATION


def panicle_rows(compactness: str, shape: str, study: str) -> list[DescriptorObservation]:
    compactness_code = PANICLE_COMPACTNESS.grin_codes[compactness]
    shape_code = PANICLE_SHAPE.grin_codes[shape]
    trait = PANICLE_TRAIT.trait_id
    return [
        DescriptorObservation("PI 1", PANICLE_COMPACTNESS.code, compactness, compactness_code, trait, "", study, "u"),
        DescriptorObservation(
            "PI 1", PANICLE_SHAPE.code, shape, shape_code, trait, ibpgr_state_for(PANICLE_SHAPE, shape)[1], study, "u"
        ),
        DescriptorObservation(
            "PI 1", COMBINED_PANICLE_DESCRIPTOR, f"{compactness} / {shape}", f"{compactness_code}+{shape_code}",
            trait, combined_panicle_state(compactness_code, shape_code), study, "u",
        ),
    ]


def test_panicle_uses_the_combined_row_of_a_study():
    # The separate compactness and shape rows carry no state; the combined row does.
    label = trait_labels(PANICLE_TRAIT, {"PI 1"}, panicle_rows("Compact", "Oval", "S1"))["PI 1"]
    assert label == AccessionTrait("10", None, ("Compact / Oval",))


def test_loose_elliptical_panicles_have_no_single_state():
    # IBPGR splits loose panicles by branch habit, which GRIN does not record.
    label = trait_labels(PANICLE_TRAIT, {"PI 1"}, panicle_rows("Loose", "Elliptical", "S1"))["PI 1"]
    assert label.exclusion is TraitExclusion.NO_SINGLE_STATE


def test_panicle_plantings_that_disagree_are_excluded():
    rows = panicle_rows("Compact", "Elliptical", "S1") + panicle_rows("Semi-compact", "Elliptical", "S2")
    assert trait_labels(PANICLE_TRAIT, {"PI 1"}, rows)["PI 1"].exclusion is TraitExclusion.CONFLICTING_OBSERVATIONS


def test_a_study_with_only_compactness_counts_as_a_value_without_a_state():
    compactness_only = DescriptorObservation(
        "PI 1", PANICLE_COMPACTNESS.code, "Compact", "1", PANICLE_TRAIT.trait_id, "", "S2", "u"
    )
    rows = panicle_rows("Compact", "Oval", "S1") + [compactness_only]
    assert trait_labels(PANICLE_TRAIT, {"PI 1"}, rows)["PI 1"].exclusion is TraitExclusion.CONFLICTING_OBSERVATIONS


def test_a_label_has_a_state_or_an_exclusion():
    with pytest.raises(ValueError):
        AccessionTrait("5", TraitExclusion.NO_OBSERVATION, ())
    with pytest.raises(ValueError):
        AccessionTrait("", None, ())


def photo(accession: str, state: str, split: Split = Split.TRAIN) -> TraitPhoto:
    return TraitPhoto(f"{accession}.jpg", accession, accession, "P", split, "", {"glumeColour": state})


def test_head_states_need_enough_training_accessions_and_keep_catalogue_order():
    photos = [photo(f"A{i}", "6") for i in range(3)] + [photo(f"B{i}", "1") for i in range(2)]
    photos += [photo("C0", "4"), photo("C0", "4")]  # one accession, two photos: counts once
    photos += [photo(f"D{i}", "4", Split.TEST) for i in range(5)]  # test accessions never count
    assert head_states(photos, GLUME_COLOUR_TRAIT, min_train_accessions=2) == ("1", "6")
    assert head_states(photos, GLUME_COLOUR_TRAIT, min_train_accessions=3) == ("6",)
    assert head_states(photos, GLUME_COLOUR_TRAIT, min_train_accessions=4) == ()
