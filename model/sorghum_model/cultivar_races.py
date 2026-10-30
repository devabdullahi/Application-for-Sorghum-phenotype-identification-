"""The race label of each photographed accession, and why some accessions have none.

Race (Harlan & de Wet 1972) is the "sorghum type" that ADR-0011 scores the 89% target on. GRIN
records it per accession and planting (`grin_descriptors.RACE`). An accession gets a scored
race only when every GRIN race observation of it names the same one of the fifteen races. All
other accessions keep their photos in the split, for trait heads, but carry no race label, so
they are neither trained on nor scored by the race model. Each such accession records why:

- `no-race-observation`: GRIN has no race value for it.
- `race-unknown`: GRIN's own "Unknown" race code (17).
- `not-a-race`: the value names something other than one race. "Shattercane" (code 16) is the
  weedy, shattering form of S. bicolor, which Harlan & de Wet do not class as a race. "Mixed"
  is a seed lot of several races, and "Breeding line" a pedigree status; neither has a GRIN
  race code.
- `unmapped-value`: a value missing from GRIN's race code table (GRIN added a value). Kept apart
  from `not-a-race` so a new value is seen and mapped, not silently dropped.
- `conflicting-observations`: plantings disagree on the race (e.g. Durra in one study,
  Durra-bicolor in another). Picking one would be a guess; CLAUDE.md: never guess a label.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from sorghum_model.grin_descriptors import RACE, DescriptorObservation

# GRIN race codes 01-15: the five basic races and their ten intermediates. 16 (Shattercane)
# and 17 (Unknown) are in GRIN's table but are not races.
SCORED_RACE_CODES: frozenset[str] = frozenset(f"{code:02d}" for code in range(1, 16))
UNKNOWN_RACE_CODE = "17"

# Values GRIN uses that are known not to name one race; see the module docstring.
NOT_A_RACE_VALUES: frozenset[str] = frozenset({"shattercane", "mixed", "breeding line"})


class RaceExclusion(Enum):
    """Why an accession has no scored race. The value is written to the split manifest."""

    NO_RACE_OBSERVATION = "no-race-observation"
    RACE_UNKNOWN = "race-unknown"
    NOT_A_RACE = "not-a-race"
    UNMAPPED_VALUE = "unmapped-value"
    CONFLICTING_OBSERVATIONS = "conflicting-observations"


@dataclass(frozen=True)
class AccessionRace:
    """The race label of one accession: exactly one of `race` and `exclusion` is set.

    Attributes:
        race: GRIN's race name ("Durra-bicolor"), or "" when excluded.
        exclusion: why there is no race, or None when `race` is set.
        observed_values: every distinct GRIN race value recorded for the accession, sorted,
            so a reader can check an exclusion without opening the descriptor manifest.
    """

    race: str
    exclusion: RaceExclusion | None
    observed_values: tuple[str, ...]

    def __post_init__(self) -> None:
        if bool(self.race) == (self.exclusion is not None):
            raise ValueError("an accession has either a race or an exclusion, not both or neither")


def race_labels(accessions: Iterable[str], observations: Iterable[DescriptorObservation]) -> dict[str, AccessionRace]:
    """Returns the race label of every accession in `accessions` (see the module docstring)."""
    values_by_accession: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        if observation.descriptor == RACE.code:
            values_by_accession[observation.accession].add(" ".join(observation.grin_value.split()))

    return {accession: _race_label(values_by_accession.get(accession, set())) for accession in accessions}


def _race_label(values: set[str]) -> AccessionRace:
    observed = tuple(sorted(values))
    if not values:
        return AccessionRace("", RaceExclusion.NO_RACE_OBSERVATION, observed)
    # Compared case-insensitively, as GRIN capitalises the same value differently across studies.
    if len({value.lower() for value in values}) > 1:
        return AccessionRace("", RaceExclusion.CONFLICTING_OBSERVATIONS, observed)

    value = observed[0]
    if value.lower() in NOT_A_RACE_VALUES:
        return AccessionRace("", RaceExclusion.NOT_A_RACE, observed)
    codes_by_label = {label.lower(): code for label, code in RACE.grin_codes.items()}
    code = codes_by_label.get(value.lower())
    if code == UNKNOWN_RACE_CODE:
        return AccessionRace("", RaceExclusion.RACE_UNKNOWN, observed)
    if code not in SCORED_RACE_CODES:
        return AccessionRace("", RaceExclusion.UNMAPPED_VALUE, observed)
    # GRIN's table spelling, so one race is always written the same way.
    canonical = next(label for label, label_code in RACE.grin_codes.items() if label_code == code)
    return AccessionRace(canonical, None, observed)
