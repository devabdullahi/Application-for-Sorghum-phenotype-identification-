"""Accession identity and race labels across GRIN-Global, ICRISAT and the Frontiers 2023 panel.

ADR-0011 scores the type target on GRIN's race labels, so their reliability caps any race
metric. This module matches every sample of the Frontiers 2023 race panel (`frontiers_races`)
to a GRIN accession, keeps each source's own race label, and reports how often they agree.

Identity. A Frontiers name is a PI, NSL or IS number. It is **matched** when exactly one GRIN
sorghum accession lists that number on its detail page (`grin_accessions`), **ambiguous** when
several do, and **failed** when none does or the name is not a genebank number. The GRIN page
also gives the ICRISAT IS number, which links the accession to the ICRISAT genebank.

Race. GRIN's label is the one the race model uses (`cultivar_races.race_labels` over every GRIN
race study), so an accession with conflicting GRIN observations has no GRIN race here either.
Races are compared by their basic-race parents, because the two sources write intermediates
in different orders ("Bicolor-caudatum" and GRIN's "Caudatum-bicolor" are one race):

- `same-race`: the same basic race, or the same intermediate.
- `basic-vs-intermediate`: one source names a basic race, the other an intermediate of it.
- `intermediates-share-a-parent`: two different intermediates with one parent in common.
- `different-race`: no parent in common.
- `not-compared`: identity not matched, or one source has no race; the reason says which.

ICRISAT's own race label (Genesys passport data) is not read: the Genesys API answered HTTP
401 (bearer token required) on 2026-10-30, and its download needs a login. The columns are kept
so the label can be added once the export exists.
"""

import csv
import math
import os
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from enum import Enum
from pathlib import Path

from sorghum_model.cultivar_races import AccessionRace
from sorghum_model.frontiers_races import FRONTIERS_SOURCE, FrontiersSample
from sorghum_model.grin_accessions import (
    AccessionDetail,
    detail_url,
    normalized_number,
    parse_accession_detail,
    parse_search_results,
    search_url,
)

# The five basic races (Harlan & de Wet 1972), in the order the product goal names them.
BASIC_RACES: tuple[str, ...] = ("Bicolor", "Guinea", "Caudatum", "Kafir", "Durra")

# GRIN's plant introduction numbers; the other Frontiers numbers (IS, NSL) belong to other
# genebanks and are only listed on the GRIN accession.
GRIN_ACCESSION_PREFIX = "PI "

GENESYS_NOT_FETCHED = "not fetched: Genesys API needs a bearer token (HTTP 401, 2026-10-30)"

# z for a two-sided 95% interval.
Z_95 = 1.959964


class IdentityStatus(Enum):
    """Whether a sample's genebank number names exactly one GRIN accession."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class RaceComparison(Enum):
    """How two race labels relate; see the module docstring."""

    SAME = "same-race"
    BASIC_VS_INTERMEDIATE = "basic-vs-intermediate"
    INTERMEDIATES_SHARE_A_PARENT = "intermediates-share-a-parent"
    DIFFERENT = "different-race"
    NOT_COMPARED = "not-compared"


@dataclass(frozen=True)
class IdentityResolution:
    """The GRIN accession a genebank number names, or why there is none.

    `detail` is set only when `status` is MATCHED.
    """

    status: IdentityStatus
    reason: str
    detail: AccessionDetail | None = None
    detail_id: str = ""


@dataclass(frozen=True)
class CrosswalkRow:
    """One Frontiers sample with its identity in GRIN and ICRISAT and each source's race.

    Written as one row of `manifests/race-crosswalk-frontiers.csv`. Blank strings mean
    "not known"; `identity_reason` and `comparison_reason` say why.
    """

    source: str
    sample_id: str
    name: str
    frontiers_race: str
    frontiers_reference: str
    genebank_number: str
    identity_status: str
    identity_reason: str
    grin_accession: str
    grin_detail_id: str
    icrisat_number: str
    grin_race: str
    grin_race_exclusion: str
    grin_race_values: str
    grin_race_studies: int
    grin_photographed: str
    grin_accession_split: str
    genesys_race: str
    genesys_provenance: str
    race_comparison: str
    comparison_reason: str


CROSSWALK_COLUMNS = [field.name for field in fields(CrosswalkRow)]


def basic_parents(race: str) -> frozenset[str]:
    """The basic races a race name is made of ({"Caudatum", "Bicolor"} for "Bicolor-caudatum").

    Empty when the name is not a race ("Unknown", "Mixed", "").
    """
    parts = [part.strip().capitalize() for part in race.split("-")]
    if not race.strip() or len(parts) > 2 or any(part not in BASIC_RACES for part in parts):
        return frozenset()
    return frozenset(parts)


def compare_races(first: str, second: str) -> RaceComparison:
    """How two race names relate (module docstring); NOT_COMPARED when either is not a race."""
    first_parents, second_parents = basic_parents(first), basic_parents(second)
    if not first_parents or not second_parents:
        return RaceComparison.NOT_COMPARED
    if first_parents == second_parents:
        return RaceComparison.SAME
    if not first_parents & second_parents:
        return RaceComparison.DIFFERENT
    if len(first_parents) == 1 or len(second_parents) == 1:
        return RaceComparison.BASIC_VS_INTERMEDIATE
    return RaceComparison.INTERMEDIATES_SHARE_A_PARENT


def resolve_genebank_number(
    number: str, fetch_page: Callable[[str], str], max_candidates: int
) -> IdentityResolution:
    """Finds the one GRIN sorghum accession whose detail page lists `number`.

    Every sorghum hit of GRIN's search (up to `max_candidates`, in GRIN's order) is opened and
    checked, so two accessions listing the same number are reported as ambiguous rather than
    the first one being taken. For a PI number only the hit with that accession number is
    opened, because the fuzzy search also returns other PIs that share its digits.
    """
    if not number:
        return IdentityResolution(IdentityStatus.FAILED, "name is not a genebank number (PI, NSL or IS)")
    hits = [hit for hit in parse_search_results(fetch_page(search_url(number))) if hit.is_sorghum]
    if number.startswith(GRIN_ACCESSION_PREFIX):
        # A PI number is GRIN's own accession number, so only the hit with that number can be it.
        hits = [hit for hit in hits if normalized_number(hit.accession) == normalized_number(number)]
    listing = []
    for hit in hits[:max_candidates]:
        detail = parse_accession_detail(fetch_page(detail_url(hit.detail_id)))
        if detail.lists(number):
            listing.append((hit.detail_id, detail))
    checked = f"{min(len(hits), max_candidates)} of {len(hits)} sorghum search hits checked"
    if not listing:
        return IdentityResolution(IdentityStatus.FAILED, f"no GRIN sorghum accession lists {number} ({checked})")
    if len(listing) > 1:
        accessions = ", ".join(detail.accession for _, detail in listing)
        return IdentityResolution(IdentityStatus.AMBIGUOUS, f"{len(listing)} GRIN accessions list {number}: {accessions}")
    detail_id, detail = listing[0]
    how = "is its accession number" if detail.accession.replace(" ", "") == number.replace(" ", "") else "is listed"
    return IdentityResolution(IdentityStatus.MATCHED, f"{number} {how} on GRIN {detail.accession}", detail, detail_id)


def crosswalk_row(
    sample: FrontiersSample,
    identity: IdentityResolution,
    grin_race: AccessionRace | None,
    grin_race_studies: int,
    accession_split: str,
) -> CrosswalkRow:
    """Joins one sample's identity and both race labels, and compares the races.

    `grin_race` is the GRIN label of the matched accession (None when not matched) and
    `accession_split` its split in `cultivar-grin-v1.csv`, or "" when GRIN has no photo of it.
    """
    detail = identity.detail
    race = grin_race.race if grin_race else ""
    comparison, reason = _comparison(sample, identity, grin_race)
    return CrosswalkRow(
        source=FRONTIERS_SOURCE,
        sample_id=sample.sample_id,
        name=sample.name,
        frontiers_race=sample.race,
        frontiers_reference=sample.reference,
        genebank_number=sample.genebank_number,
        identity_status=identity.status.value,
        identity_reason=identity.reason,
        grin_accession=detail.accession if detail else "",
        grin_detail_id=identity.detail_id,
        icrisat_number=" + ".join(detail.icrisat_numbers) if detail else "",
        grin_race=race,
        grin_race_exclusion=grin_race.exclusion.value if grin_race and grin_race.exclusion else "",
        grin_race_values=" + ".join(grin_race.observed_values) if grin_race else "",
        grin_race_studies=grin_race_studies,
        grin_photographed="yes" if accession_split else "no",
        grin_accession_split=accession_split,
        genesys_race="",
        genesys_provenance=GENESYS_NOT_FETCHED,
        race_comparison=comparison.value,
        comparison_reason=reason,
    )


def _comparison(
    sample: FrontiersSample, identity: IdentityResolution, grin_race: AccessionRace | None
) -> tuple[RaceComparison, str]:
    if identity.status is not IdentityStatus.MATCHED:
        return RaceComparison.NOT_COMPARED, f"identity {identity.status.value}"
    if grin_race is None or grin_race.exclusion is not None:
        exclusion = grin_race.exclusion.value if grin_race else "no-race-observation"
        values = " + ".join(grin_race.observed_values) if grin_race else ""
        return RaceComparison.NOT_COMPARED, f"GRIN has no scored race ({exclusion}{': ' + values if values else ''})"
    if not basic_parents(sample.race):
        return RaceComparison.NOT_COMPARED, f"Frontiers race '{sample.race}' is not a race name"
    comparison = compare_races(sample.race, grin_race.race)
    if comparison is RaceComparison.SAME:
        return comparison, ""
    return comparison, f"{comparison.value}: Frontiers {sample.race}, GRIN {grin_race.race}"


def write_crosswalk(rows: Iterable[CrosswalkRow], path: Path) -> None:
    """Writes the crosswalk sorted by Frontiers race and name, via a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CROSSWALK_COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (r.frontiers_race, r.name, r.sample_id)):
            writer.writerow(asdict(row))
    temporary.replace(path)


def read_crosswalk(path: Path) -> list[CrosswalkRow]:
    """Reads a file written by `write_crosswalk`."""
    with path.open(newline="", encoding="utf-8") as file:
        return [
            CrosswalkRow(**{**row, "grin_race_studies": int(row["grin_race_studies"])}) for row in csv.DictReader(file)
        ]


def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval of a binomial proportion; (0, 1) when there are no trials.

    Chosen over the normal approximation because several races have under 20 compared
    accessions and agreement near 1, where the normal interval leaves [0, 1].
    """
    if trials == 0:
        return 0.0, 1.0
    proportion = successes / trials
    denominator = 1 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    half_width = z * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def frontiers_race_group(race: str) -> str:
    """The reporting group of a Frontiers race: its basic race, or "Intermediate"."""
    parents = basic_parents(race)
    if len(parents) == 1:
        return next(iter(parents))
    return "Intermediate" if parents else "(not a race)"


def crosswalk_report(rows: list[CrosswalkRow]) -> list[str]:
    """The summary lines committed next to the crosswalk: identity, then race agreement."""
    return _identity_lines(rows) + [""] + _agreement_lines(rows) + [""] + _mismatch_lines(rows)


def _identity_lines(rows: list[CrosswalkRow]) -> list[str]:
    lines = [
        "Identity (Frontiers 2023 Table 1 sample -> GRIN-Global accession)",
        f"  {'name type':12} {'samples':>8} {'matched':>8} {'ambiguous':>10} {'failed':>7} {'photographed':>13}",
    ]

    def name_type(row: CrosswalkRow) -> str:
        return row.genebank_number.split(" ")[0] if row.genebank_number else "sample name"

    for kind in sorted({name_type(row) for row in rows}) + ["all"]:
        in_kind = [row for row in rows if kind in ("all", name_type(row))]
        status = Counter(row.identity_status for row in in_kind)
        photographed = sum(row.grin_photographed == "yes" for row in in_kind)
        lines.append(
            f"  {kind:12} {len(in_kind):>8} {status['matched']:>8} {status['ambiguous']:>10} "
            f"{status['failed']:>7} {photographed:>13}"
        )
    matched = [row for row in rows if row.identity_status == IdentityStatus.MATCHED.value]
    without_race = Counter(row.grin_race_exclusion for row in matched if not row.grin_race)
    lines.append(
        f"  matched with a scored GRIN race: {sum(bool(row.grin_race) for row in matched)} of {len(matched)}"
        + (f"; without: {', '.join(f'{key} {count}' for key, count in sorted(without_race.items()))}" if without_race else "")
    )
    lines.append(f"  matched with an ICRISAT IS number on GRIN: {sum(bool(row.icrisat_number) for row in matched)}")
    return lines


def _agreement_lines(rows: list[CrosswalkRow]) -> list[str]:
    compared = [row for row in rows if row.race_comparison != RaceComparison.NOT_COMPARED.value]
    header = (
        f"  {'Frontiers race':16} {'n':>4} {'same':>5} {'b-vs-i':>7} {'share':>6} {'diff':>5}"
        f" {'exact agreement [95% CI]':>27} {'same or b-vs-i [95% CI]':>27}"
    )
    lines = [
        "Race agreement, Frontiers vs GRIN (matched accessions with a race in both; Wilson 95% CI)",
        "  b-vs-i: one names a basic race, the other an intermediate of it; share: two intermediates",
        "  with a common parent; diff: no parent in common.",
        header,
    ]
    groups = [*BASIC_RACES, "Intermediate"]
    for group in groups + ["all"]:
        in_group = [row for row in compared if group == "all" or frontiers_race_group(row.frontiers_race) == group]
        lines.append(_agreement_line(group, in_group))
    both_basic = [
        row for row in compared if len(basic_parents(row.frontiers_race)) == 1 and len(basic_parents(row.grin_race)) == 1
    ]
    lines.append(_agreement_line("both basic", both_basic))
    return lines


def _agreement_line(label: str, rows: list[CrosswalkRow]) -> str:
    counts = Counter(row.race_comparison for row in rows)
    same = counts[RaceComparison.SAME.value]
    compatible = same + counts[RaceComparison.BASIC_VS_INTERMEDIATE.value]
    return (
        f"  {label:16} {len(rows):>4} {same:>5} {counts[RaceComparison.BASIC_VS_INTERMEDIATE.value]:>7}"
        f" {counts[RaceComparison.INTERMEDIATES_SHARE_A_PARENT.value]:>6} {counts[RaceComparison.DIFFERENT.value]:>5}"
        f" {_rate(same, len(rows)):>27} {_rate(compatible, len(rows)):>27}"
    )


def _rate(successes: int, trials: int) -> str:
    if trials == 0:
        return "-"
    low, high = wilson_interval(successes, trials)
    return f"{successes}/{trials} {successes / trials:.2f} [{low:.2f}, {high:.2f}]"


def _mismatch_lines(rows: list[CrosswalkRow]) -> list[str]:
    mismatched = [
        row
        for row in rows
        if row.race_comparison not in (RaceComparison.SAME.value, RaceComparison.NOT_COMPARED.value)
    ]
    lines = [f"Race mismatches ({len(mismatched)})"]
    for row in sorted(mismatched, key=lambda r: (r.race_comparison, r.frontiers_race, r.name)):
        lines.append(
            f"  {row.name:10} {row.grin_accession:10} {row.comparison_reason}"
            f" (GRIN values: {row.grin_race_values}; {row.grin_race_studies} GRIN studies)"
        )
    return lines
