"""Ranks GRIN-Global accessions to request as seed for the type evaluation (`type-eval-v1`).

The protocol (docs/architecture/type-evaluation-protocol.md) needs 150 accessions per basic
race: 100 for development and 50 for a sealed test. This module proposes them from every
accession GRIN has a race observation for (its race study pages, already cached by
`grin-descriptors`), with alternates and a placeholder seed quantity.

Who can be a candidate (protocol 5.2): the accession's GRIN race label is one basic race with no
conflicting GRIN observation (`cultivar_races.race_labels`), no second source names another
race (`race_crosswalk`, Frontiers 2023), and a GRIN study page shows an orderable seed lot.
Candidates that fail a rule are counted by reason. They are never used to fill a shortfall.

Ranking inside a race, best first:

1. **Label confidence** (`LabelTier`): Frontiers names the same race, then two or more GRIN
   plantings agree, then a single GRIN observation.
2. **Descriptor coverage**: how many catalogue traits GRIN has IBPGR states for. A test of
   trait-first matching needs them.
3. A fixed pseudo-random order (SHA-256 of the accession), so ties are not broken by PI number,
   which follows collection date and origin.

Then no origin country may take more than `max_origin_share` of a race's core while candidates
from other origins are left. This keeps the test from being one country's landraces. Finally,
the core keeps at least `test_per_race` test-eligible accessions where it can. A test-eligible
accession has a confirmed label (two agreeing observations, protocol 5.2) and no GRIN photo in the
`accession_split` train or validation split (protocol 5.3). A race with too few is reported as a
shortfall. It is not filled with single-observation labels.
"""

import csv
import hashlib
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from enum import Enum
from pathlib import Path

from sorghum_model.cultivar_races import AccessionRace
from sorghum_model.grin_accessions import StudyRosterRow, detail_url
from sorghum_model.race_crosswalk import BASIC_RACES, CrosswalkRow, IdentityStatus, RaceComparison, basic_parents
from sorghum_model.settings import CoreShortlistSettings

TEST_INELIGIBLE_SPLITS = frozenset({"train", "validation"})


class LabelTier(Enum):
    """How well the race label of a candidate is supported; first is best."""

    CORROBORATED = "corroborated"  # Frontiers 2023 names the same basic race
    REPEATED = "repeated"  # two or more GRIN plantings, all the same race
    SINGLE = "single"  # one GRIN observation

    @property
    def rank(self) -> int:
        return list(LabelTier).index(self)


class Exclusion(Enum):
    """Why an accession GRIN names as one basic race is not a candidate."""

    SECOND_SOURCE_DISAGREES = "second-source-disagrees"
    NO_ORDERABLE_SEED = "no-orderable-seed"


@dataclass(frozen=True)
class AccessionPassport:
    """What the shortlist knows about one GRIN accession before ranking.

    Attributes:
        roster: the accession's first row on a GRIN race study page (detail id, name, origin).
        orderable: some study page shows an orderable seed lot of it.
        race: its GRIN race label.
        race_studies: how many GRIN plantings recorded its race.
        traits_with_states: catalogue trait ids GRIN has an IBPGR state for.
        frontiers: its row in the Frontiers crosswalk, or None.
        grin_accession_split: its split in `cultivar-grin-v1.csv`, or "" when GRIN has no photo.
    """

    roster: StudyRosterRow
    orderable: bool
    race: AccessionRace
    race_studies: int
    traits_with_states: frozenset[str]
    frontiers: CrosswalkRow | None
    grin_accession_split: str


@dataclass(frozen=True)
class ShortlistRow:
    """One row of `manifests/core-accession-shortlist.csv`."""

    race: str
    rank: int
    role: str
    test_eligible: str
    accession: str
    icrisat_number: str
    name: str
    origin: str
    label_tier: str
    grin_race_studies: int
    grin_race_values: str
    frontiers_race: str
    descriptor_traits: int
    descriptor_trait_ids: str
    grin_accession_split: str
    seed_request_seeds: int
    grin_url: str


SHORTLIST_COLUMNS = [field.name for field in fields(ShortlistRow)]


def accession_availability(rows: Iterable[StudyRosterRow]) -> dict[str, bool]:
    """Accession -> orderable on any of its study rows (each row describes one seed lot)."""
    orderable: dict[str, bool] = defaultdict(bool)
    for row in rows:
        orderable[row.accession] |= row.availability.is_orderable
    return dict(orderable)


def label_tier(passport: AccessionPassport) -> LabelTier:
    if passport.frontiers is not None and passport.frontiers.race_comparison == RaceComparison.SAME.value:
        return LabelTier.CORROBORATED
    if passport.race_studies >= 2:
        return LabelTier.REPEATED
    return LabelTier.SINGLE


def exclusion_of(passport: AccessionPassport) -> Exclusion | None:
    """Why a basic-race accession cannot be shortlisted, or None when it can."""
    frontiers = passport.frontiers
    if frontiers is not None and frontiers.race_comparison not in (
        RaceComparison.SAME.value,
        RaceComparison.NOT_COMPARED.value,
    ):
        return Exclusion.SECOND_SOURCE_DISAGREES
    if not passport.orderable:
        return Exclusion.NO_ORDERABLE_SEED
    return None


def is_test_eligible(passport: AccessionPassport) -> bool:
    """Protocol 5.2-5.3: a confirmed label (not a single observation) and no GRIN photo in train
    or validation. A specialist's blind check can later confirm a single-observation label."""
    return label_tier(passport) is not LabelTier.SINGLE and passport.grin_accession_split not in TEST_INELIGIBLE_SPLITS


def origin_country(origin: str) -> str:
    """The country of a GRIN origin ("Transvaal, South Africa" -> "South Africa")."""
    return origin.split(",")[-1].strip() or "(unknown)"


def basic_race_of(passport: AccessionPassport) -> str:
    """The basic race of a passport's GRIN label, or "" for an intermediate or no label."""
    parents = basic_parents(passport.race.race)
    return next(iter(parents)) if len(parents) == 1 else ""


def ranked(passports: list[AccessionPassport], max_origin_share: float, core_size: int) -> list[AccessionPassport]:
    """Candidates of one race, best first (module docstring), with the origin cap applied."""
    ordered = sorted(
        passports,
        key=lambda p: (
            label_tier(p).rank,
            -len(p.traits_with_states),
            hashlib.sha256(p.roster.accession.encode()).hexdigest(),
        ),
    )
    max_per_origin = max(1, int(max_origin_share * core_size))
    taken: Counter[str] = Counter()
    first, deferred = [], []
    for passport in ordered:
        origin = origin_country(passport.roster.origin)
        if taken[origin] < max_per_origin:
            taken[origin] += 1
            first.append(passport)
        else:
            deferred.append(passport)
    return first + deferred


def select_core(ordered: list[AccessionPassport], settings: CoreShortlistSettings) -> list[AccessionPassport]:
    """The core of one race: the best `core_accessions_per_race`, keeping enough test-eligible ones.

    When the top of the ranking has fewer than `test_per_race` test-eligible accessions, the
    lowest-ranked ineligible core accessions give way to the best eligible ones outside it.
    The result keeps ranking order.
    """
    core = ordered[: settings.core_accessions_per_race]
    eligible_outside = [p for p in ordered[settings.core_accessions_per_race :] if is_test_eligible(p)]
    missing = settings.test_per_race - sum(is_test_eligible(p) for p in core)
    for _ in range(max(0, missing)):
        ineligible = [p for p in core if not is_test_eligible(p)]
        if not ineligible or not eligible_outside:
            break
        core.remove(ineligible[-1])
        core.append(eligible_outside.pop(0))
    position = {passport.roster.accession: index for index, passport in enumerate(ordered)}
    return sorted(core, key=lambda p: position[p.roster.accession])


def shortlist(passports: Iterable[AccessionPassport], settings: CoreShortlistSettings) -> tuple[list[ShortlistRow], list[str]]:
    """The shortlist rows of all five races and the summary lines that explain them."""
    by_race: dict[str, list[AccessionPassport]] = defaultdict(list)
    for passport in passports:
        race = basic_race_of(passport)
        if race:
            by_race[race].append(passport)

    rows: list[ShortlistRow] = []
    lines = _summary_header(settings)
    for race in BASIC_RACES:
        pool = by_race.get(race, [])
        exclusions = Counter(exclusion_of(p) for p in pool)
        candidates = [p for p in pool if exclusion_of(p) is None]
        ordered = ranked(candidates, settings.max_origin_share, settings.core_accessions_per_race)
        core = select_core(ordered, settings)
        core_names = {p.roster.accession for p in core}
        alternates = [p for p in ordered if p.roster.accession not in core_names][: settings.alternates_per_race]
        for rank, (passport, role) in enumerate([(p, "core") for p in core] + [(p, "alternate") for p in alternates], 1):
            rows.append(_row(race, rank, role, passport, settings))
        lines += _race_lines(race, pool, exclusions, candidates, core, alternates, settings)
    return rows, lines


def _row(race: str, rank: int, role: str, passport: AccessionPassport, settings: CoreShortlistSettings) -> ShortlistRow:
    roster = passport.roster
    name = roster.name
    frontiers = passport.frontiers
    icrisat = frontiers.icrisat_number if frontiers and frontiers.icrisat_number else ""
    # GRIN shows the ICRISAT number as the accession's top name for most ICRISAT donations.
    if not icrisat and name.upper().startswith("IS "):
        icrisat = name
    return ShortlistRow(
        race=race,
        rank=rank,
        role=role,
        test_eligible="yes" if is_test_eligible(passport) else "no",
        accession=roster.accession,
        icrisat_number=icrisat,
        name=name,
        origin=roster.origin,
        label_tier=label_tier(passport).value,
        grin_race_studies=passport.race_studies,
        grin_race_values=" + ".join(passport.race.observed_values),
        frontiers_race=frontiers.frontiers_race if frontiers else "",
        descriptor_traits=len(passport.traits_with_states),
        descriptor_trait_ids=" ".join(sorted(passport.traits_with_states)),
        grin_accession_split=passport.grin_accession_split,
        seed_request_seeds=settings.seeds_per_request,
        grin_url=detail_url(roster.detail_id),
    )


def _summary_header(settings: CoreShortlistSettings) -> list[str]:
    return [
        "Core accession shortlist (type-eval-v1, T26)",
        f"  target per race: {settings.core_accessions_per_race} core "
        f"({settings.development_per_race} development + {settings.test_per_race} test), "
        f"{settings.alternates_per_race} alternates; at most {settings.max_origin_share:.0%} of a core from one origin "
        "while others are left",
        f"  seed request (placeholder rule): {settings.seeds_per_request} seeds per core and alternate accession",
        "",
    ]


def _race_lines(
    race: str,
    pool: list[AccessionPassport],
    exclusions: Counter,
    candidates: list[AccessionPassport],
    core: list[AccessionPassport],
    alternates: list[AccessionPassport],
    settings: CoreShortlistSettings,
) -> list[str]:
    tiers = Counter(label_tier(p).value for p in core)
    eligible = sum(is_test_eligible(p) for p in core)
    origins = Counter(origin_country(p.roster.origin) for p in core)
    shortfall = []
    if len(core) < settings.core_accessions_per_race:
        shortfall.append(f"core short by {settings.core_accessions_per_race - len(core)}")
    if eligible < settings.test_per_race:
        shortfall.append(f"test-eligible short by {settings.test_per_race - eligible}")
    if len(alternates) < settings.alternates_per_race:
        shortfall.append(f"alternates short by {settings.alternates_per_race - len(alternates)}")
    top_origins = ", ".join(f"{origin} {count}" for origin, count in origins.most_common(3))
    return [
        f"{race}",
        f"  GRIN accessions labelled {race}: {len(pool)}; excluded: "
        + ", ".join(f"{e.value} {exclusions[e]}" for e in Exclusion)
        + f"; candidates: {len(candidates)}",
        "  candidate label tiers: "
        + ", ".join(f"{tier.value} {sum(label_tier(p) is tier for p in candidates)}" for tier in LabelTier),
        f"  core: {len(core)} (test-eligible {eligible}); alternates: {len(alternates)}",
        "  core label tiers: " + ", ".join(f"{tier.value} {tiers[tier.value]}" for tier in LabelTier),
        f"  core origins: {len(origins)} countries (top: {top_origins})",
        f"  shortfall: {'; '.join(shortfall) if shortfall else 'none'}",
        "",
    ]


def frontiers_by_accession(rows: Iterable[CrosswalkRow]) -> dict[str, CrosswalkRow]:
    """Matched crosswalk rows by GRIN accession (the first row when one accession has two samples)."""
    by_accession: dict[str, CrosswalkRow] = {}
    for row in rows:
        if row.identity_status == IdentityStatus.MATCHED.value:
            by_accession.setdefault(row.grin_accession, row)
    return by_accession


def write_shortlist(rows: list[ShortlistRow], path: Path) -> None:
    """Writes the shortlist in race and rank order, via a temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SHORTLIST_COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (BASIC_RACES.index(r.race), r.rank)):
            writer.writerow(asdict(row))
    temporary.replace(path)

