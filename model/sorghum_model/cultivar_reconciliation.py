"""Checks that the cultivar split, the GRIN study listings and the descriptors add up.

`cultivar-split` writes these lines next to the split (`splits/cultivar-grin-v1-summary.txt`),
so the committed numbers can be checked without the images: how many photos GRIN lists, how
many were downloaded, how many accessions have descriptors and a scored race, why the rest
are excluded, and the size of every split and race.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from sorghum_model.cultivar_races import AccessionRace, RaceExclusion
from sorghum_model.grin_descriptors import DescriptorObservation
from sorghum_model.splits import Split

# How many example keys a line lists when it reports a mismatch.
EXAMPLES_SHOWN = 10


@dataclass(frozen=True)
class ListedImage:
    """One image a GRIN study page lists: its manifest `source_id` and its accession."""

    source_id: str
    accession: str


def reconciliation_report(
    split_rows: list[dict[str, str]],
    listed_images: list[ListedImage],
    observations: list[DescriptorObservation],
    races: dict[str, AccessionRace],
    repeated_rows_dropped: int,
) -> list[str]:
    """Returns the summary lines (see the module docstring).

    `split_rows` is the written split (`read_cultivar_split`), `listed_images` every image on
    the cached GRIN study pages, and `races` the label of every downloaded accession.
    """
    lines: list[str] = []
    lines += _image_lines(split_rows, listed_images, repeated_rows_dropped)
    lines += _descriptor_lines(split_rows, listed_images, observations)
    lines += _race_label_lines(split_rows, races)
    lines += _split_lines(split_rows)
    lines += _race_support_lines(split_rows)
    return lines


def _image_lines(rows: list[dict[str, str]], listed: list[ListedImage], repeated: int) -> list[str]:
    listed_ids = {image.source_id for image in listed}
    downloaded_ids = {row["source_id"] for row in rows}
    not_downloaded = sorted(listed_ids - downloaded_ids)
    not_listed = sorted(downloaded_ids - listed_ids)
    plantings = {source_id.split("/")[0] for source_id in listed_ids}
    return [
        "Images",
        f"  listed on the GRIN study pages: {len(listed_ids)} images of "
        f"{len({image.accession for image in listed})} accessions in {len(plantings)} plantings",
        f"  manifest rows: {len(rows) + repeated} ({repeated} exact repeats dropped)",
        f"  downloaded: {len(rows)} images of {len({row['cultivar_label'] for row in rows})} accessions",
        f"  listed but not downloaded: {len(not_downloaded)} {_examples(not_downloaded)}",
        f"  downloaded but not listed: {len(not_listed)} {_examples(not_listed)}",
        "",
    ]


def _descriptor_lines(
    rows: list[dict[str, str]], listed: list[ListedImage], observations: list[DescriptorObservation]
) -> list[str]:
    photographed = {image.accession for image in listed}
    downloaded = {row["cultivar_label"] for row in rows}
    observed = {observation.accession for observation in observations}
    not_photographed = sorted(observed - photographed)
    return [
        "Descriptors",
        f"  observations: {len(observations)} over {len(observed)} accessions",
        f"  photographed accessions with any observation: {len(photographed & observed)} of {len(photographed)}",
        f"  downloaded accessions with any observation: {len(downloaded & observed)} of {len(downloaded)}",
        f"  observed but not photographed: {len(not_photographed)} {_examples(not_photographed)}",
        "",
    ]


def _race_label_lines(rows: list[dict[str, str]], races: dict[str, AccessionRace]) -> list[str]:
    images_of_accession = Counter(row["cultivar_label"] for row in rows)
    scored = [accession for accession, race in races.items() if race.exclusion is None]
    lines = [
        "Race labels (downloaded accessions; excluded ones keep their photos for trait heads)",
        f"  scored: {len(scored)} accessions, {sum(images_of_accession[a] for a in scored)} images",
    ]
    for exclusion in RaceExclusion:
        excluded = [accession for accession, race in races.items() if race.exclusion is exclusion]
        values = Counter(" + ".join(races[accession].observed_values) or "(none)" for accession in excluded)
        shown = ", ".join(f"{value} {count}" for value, count in values.most_common(EXAMPLES_SHOWN))
        lines.append(
            f"  excluded, {exclusion.value}: {len(excluded)} accessions, "
            f"{sum(images_of_accession[a] for a in excluded)} images" + (f" [{shown}]" if excluded else "")
        )
    lines.append("")
    return lines


def _split_lines(rows: list[dict[str, str]]) -> list[str]:
    lines = ["Splits", f"  {'':12} {'accessions':>10} {'images':>8} {'scored acc.':>12} {'scored img.':>12}"]
    for column in ("accession_split", "planting_split"):
        lines.append(f"  {column}")
        for split in Split:
            in_split = [row for row in rows if row[column] == split.value]
            scored = [row for row in in_split if row["race"]]
            lines.append(
                f"  {split.value:12} {len({r['cultivar_label'] for r in in_split}):>10} {len(in_split):>8}"
                f" {len({r['cultivar_label'] for r in scored}):>12} {len(scored):>12}"
            )
    lines.append("")
    return lines


def _race_support_lines(rows: list[dict[str, str]]) -> list[str]:
    """Accessions / images per race and accession split, largest race first."""
    accessions: dict[tuple[str, str], set[str]] = defaultdict(set)
    images: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if row["race"]:
            accessions[(row["race"], row["accession_split"])].add(row["cultivar_label"])
            images[(row["race"], row["accession_split"])] += 1
    races = sorted({race for race, _ in accessions}, key=lambda r: (-sum(images[(r, s.value)] for s in Split), r))
    header = "".join(f" {split.value + ' acc/img':>20}" for split in Split)
    lines = ["Race support (accession_split)", f"  {'race':18}{header}"]
    for race in races:
        cells = "".join(
            f" {f'{len(accessions[(race, split.value)])}/{images[(race, split.value)]}':>20}" for split in Split
        )
        lines.append(f"  {race:18}{cells}")
    return lines


def _examples(keys: list[str]) -> str:
    if not keys:
        return ""
    more = f", ... {len(keys) - EXAMPLES_SHOWN} more" if len(keys) > EXAMPLES_SHOWN else ""
    return f"[{', '.join(keys[:EXAMPLES_SHOWN])}{more}]"
