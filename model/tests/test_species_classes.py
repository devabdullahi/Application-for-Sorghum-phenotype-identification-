import pytest

from sorghum_model.species_classes import SPECIES_CLASSES, SpeciesGroup, species_class


def test_exactly_one_sorghum_class_first():
    sorghum = [c for c in SPECIES_CLASSES if c.group is SpeciesGroup.SORGHUM]
    assert sorghum == [SPECIES_CLASSES[0]]


def test_johnson_grass_is_a_named_look_alike():
    assert species_class("johnson_grass").group is SpeciesGroup.LOOK_ALIKE


def test_no_taxon_is_in_two_classes():
    taxa = [t for c in SPECIES_CLASSES for t in c.inat_taxon_ids]
    assert len(taxa) == len(set(taxa))


def test_unknown_class_names_valid_ones():
    with pytest.raises(ValueError, match="sorghum_bicolor"):
        species_class("rice")
