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
        gbif_taxon_keys: GBIF backbone taxa whose human-identified occurrence photos are
            labelled with this class. Empty when GBIF adds nothing iNaturalist does not.
        commons_categories: Wikimedia Commons categories (without "Category:") whose files
            are labelled with this class. Subcategories are not followed, because they drift
            into food, art and illustrations; each useful one is listed explicitly.
    """

    name: str
    group: SpeciesGroup
    inat_taxon_ids: tuple[int, ...]
    gbif_taxon_keys: tuple[int, ...] = ()
    commons_categories: tuple[str, ...] = ()


# iNaturalist taxon ids were resolved against api.inaturalist.org/v1/taxa on 2026-10-21, GBIF
# keys against api.gbif.org/v1/species/match and Commons categories by hand on 2026-10-23.
SPECIES_CLASSES: tuple[SpeciesClass, ...] = (
    SpeciesClass(
        "sorghum_bicolor",
        SpeciesGroup.SORGHUM,
        (58389,),
        gbif_taxon_keys=(2705181,),
        commons_categories=(
            "Sorghum bicolor",
            "Sorghum bicolor (cultivated)",
            "Sorghum bicolor (seedlings)",
            "Diseases and disorders of Sorghum bicolor",
        ),
    ),
    # Johnson grass is botanically Sorghum but not a crop cultivar, so the gate names it
    # instead of passing it on to cultivar matching (decision 2026-10-21).
    SpeciesClass(
        "johnson_grass",
        SpeciesGroup.LOOK_ALIKE,
        (58387,),
        gbif_taxon_keys=(2705185,),
        commons_categories=("Sorghum halepense",),
    ),
    SpeciesClass(
        "maize",
        SpeciesGroup.LOOK_ALIKE,
        (48448,),
        gbif_taxon_keys=(5290052,),
        commons_categories=(
            "Zea mays",
            "Zea mays (seedlings)",
            "Zea mays (flowers)",
            "Zea mays leaves",
            "Maize ears",
        ),
    ),
    SpeciesClass(
        "sugarcane",
        SpeciesGroup.LOOK_ALIKE,
        (128270,),
        gbif_taxon_keys=(2703912,),
        commons_categories=("Saccharum officinarum",),
    ),
    SpeciesClass(
        "pearl_millet",
        SpeciesGroup.LOOK_ALIKE,
        (202342,),
        gbif_taxon_keys=(5828197,),  # Cenchrus americanus (syn. Pennisetum glaucum)
        commons_categories=(
            "Cenchrus americanus",
            "Cenchrus americanus (inflorescences)",
            "Cenchrus americanus (seedlings)",
            "Cenchrus americanus (seeds)",
            "Pearl millet",
        ),
    ),
    SpeciesClass(
        "finger_millet",
        SpeciesGroup.LOOK_ALIKE,
        (76789,),
        gbif_taxon_keys=(2705957,),
        commons_categories=(
            "Eleusine coracana",
            "Eleusine coracana (panicles)",
            "Eleusine coracana (seeds)",
        ),
    ),
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
        gbif_taxon_keys=(2704414, 4932035, 2704432, 2704102, 2703243),  # same five species
        commons_categories=(
            "Sorghastrum nutans",
            "Andropogon gerardii",
            "Schizachyrium scoparium",
            "Bothriochloa ischaemum",
            "Hyparrhenia hirta",
        ),
    ),
    # Dicots. GBIF is not used: iNaturalist alone has millions of research-grade dicots.
    SpeciesClass("other_plant", SpeciesGroup.OTHER_PLANT, (47124,)),  # Magnoliopsida
    # No naturalist source photographs an empty board, soil or a hand. Commons has general
    # photos of each; our own board photos are still needed (model/README.md).
    SpeciesClass(
        "no_plant",
        SpeciesGroup.NO_PLANT,
        (),
        commons_categories=(
            "Soil cracks",
            "Ground textures",
            "Unidentified soils",
            "Plywood",
            "Wooden boards",
            "Cardboard",
            "Human hands",
            "Hands",
        ),
    ),
)

SPECIES_CLASS_NAMES: tuple[str, ...] = tuple(c.name for c in SPECIES_CLASSES)


def species_class(name: str) -> SpeciesClass:
    """Returns the class called `name`, or raises ValueError naming the valid classes."""
    for candidate in SPECIES_CLASSES:
        if candidate.name == name:
            return candidate
    raise ValueError(f"Unknown species class {name!r}; expected one of {SPECIES_CLASS_NAMES}")
