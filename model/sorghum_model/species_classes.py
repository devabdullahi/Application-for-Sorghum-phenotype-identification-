"""Classes of the species head and where their training photos come from (ADR-0006).

The order of SPECIES_CLASSES is the order of the head's outputs. Changing it, or adding a
class, changes the model's output layout and requires a new model version N.
"""

from dataclasses import dataclass
from enum import Enum


class SpeciesGroup(Enum):
    """How `shared/species` treats a class when it is the top prediction."""

    SORGHUM = "sorghum"
    """Continue to calibration, traits and reasoning."""

    LOOK_ALIKE = "lookAlike"
    """Stop with "not sorghum" and name the look-alike when confident."""

    OTHER_PLANT = "otherPlant"
    """Stop with "not sorghum"."""

    NO_PLANT = "noPlant"
    """Stop and ask for a retake."""


@dataclass(frozen=True)
class SpeciesClass:
    """One output of the species head.

    Attributes:
        name: stable class id used in manifests and model metadata.
        group: decision group for `shared/species`.
        inat_taxon_ids: iNaturalist taxa whose research-grade photos are labelled with this
            class. Empty when photos only come from local imports (our own photos).
    """

    name: str
    group: SpeciesGroup
    inat_taxon_ids: tuple[int, ...]


# Taxon ids were resolved against api.inaturalist.org/v1/taxa on 2026-10-21.
SPECIES_CLASSES: tuple[SpeciesClass, ...] = (
    SpeciesClass("sorghum_bicolor", SpeciesGroup.SORGHUM, (58389,)),
    # Johnson grass is botanically Sorghum but not a crop cultivar, so the gate names it
    # instead of passing it on to cultivar matching (decision 2026-10-21).
    SpeciesClass("johnson_grass", SpeciesGroup.LOOK_ALIKE, (58387,)),
    SpeciesClass("maize", SpeciesGroup.LOOK_ALIKE, (48448,)),
    SpeciesClass("sugarcane", SpeciesGroup.LOOK_ALIKE, (128270,)),
    SpeciesClass("pearl_millet", SpeciesGroup.LOOK_ALIKE, (202342,)),
    SpeciesClass("finger_millet", SpeciesGroup.LOOK_ALIKE, (76789,)),
    # Tall andropogonoid grasses that look like sorghum: hard negatives without a name in the UI.
    SpeciesClass(
        "other_grass",
        SpeciesGroup.OTHER_PLANT,
        (
            122608,  # Sorghastrum nutans (Indiangrass)
            121968,  # Andropogon gerardi (big bluestem)
            122603,  # Schizachyrium scoparium (little bluestem)
            75842,  # Bothriochloa ischaemum (King Ranch bluestem)
            77479,  # Hyparrhenia hirta (thatching grass)
        ),
    ),
    SpeciesClass("other_plant", SpeciesGroup.OTHER_PLANT, (47124,)),  # Magnoliopsida (dicots)
    # No public source matches an empty board, soil or a hand; these come from our own photos.
    SpeciesClass("no_plant", SpeciesGroup.NO_PLANT, ()),
)

SPECIES_CLASS_NAMES: tuple[str, ...] = tuple(c.name for c in SPECIES_CLASSES)


def species_class(name: str) -> SpeciesClass:
    """Returns the class called `name`, or raises ValueError naming the valid classes."""
    for candidate in SPECIES_CLASSES:
        if candidate.name == name:
            return candidate
    raise ValueError(f"Unknown species class {name!r}; expected one of {SPECIES_CLASS_NAMES}")
