"""The cultivar split summary: listed vs downloaded images, descriptors, exclusions, support."""

from sorghum_model.cultivar_races import AccessionRace, RaceExclusion
from sorghum_model.cultivar_reconciliation import ListedImage, reconciliation_report
from sorghum_model.grin_descriptors import DescriptorObservation


def split_row(accession: str, planting: str, split: str, race: str = "", exclusion: str = "") -> dict[str, str]:
    return {
        "sha256": f"{accession}-{planting}",
        "source": "grin",
        "source_id": f"{planting}/{accession}",
        "cultivar_label": accession,
        "planting_id": planting,
        "accession_split": split,
        "planting_split": "train",
        "race": race,
        "race_exclusion": exclusion,
    }


def observation(accession: str) -> DescriptorObservation:
    return DescriptorObservation(accession, "RACE", "Durra", "05", "", "", "S", "u")


def report() -> list[str]:
    rows = [
        split_row("PI 1", "A", "train", race="Durra"),
        split_row("PI 1", "B", "train", race="Durra"),
        split_row("PI 2", "A", "test", exclusion="conflicting-observations"),
    ]
    listed = [ListedImage("A/PI 1", "PI 1"), ListedImage("B/PI 1", "PI 1"), ListedImage("A/PI 2", "PI 2"),
              ListedImage("A/PI 3", "PI 3")]
    races = {
        "PI 1": AccessionRace("Durra", None, ("Durra",)),
        "PI 2": AccessionRace("", RaceExclusion.CONFLICTING_OBSERVATIONS, ("Caudatum", "Durra")),
    }
    return reconciliation_report(rows, listed, [observation("PI 1"), observation("PI 3")], races, 1)


def test_report_reconciles_listed_and_downloaded_images():
    lines = report()
    assert "  listed on the GRIN study pages: 4 images of 3 accessions in 2 plantings" in lines
    assert "  manifest rows: 4 (1 exact repeats dropped)" in lines
    assert "  downloaded: 3 images of 2 accessions" in lines
    assert "  listed but not downloaded: 1 [A/PI 3]" in lines
    assert "  downloaded but not listed: 0 " in lines


def test_report_counts_descriptor_coverage():
    lines = report()
    assert "  photographed accessions with any observation: 2 of 3" in lines
    assert "  downloaded accessions with any observation: 1 of 2" in lines
    assert "  observed but not photographed: 0 " in lines


def test_report_counts_scored_and_excluded_accessions_with_their_values():
    lines = report()
    assert "  scored: 1 accessions, 2 images" in lines
    assert "  excluded, conflicting-observations: 1 accessions, 1 images [Caudatum + Durra 1]" in lines
    assert "  excluded, race-unknown: 0 accessions, 0 images" in lines


def test_report_gives_race_support_per_split():
    durra = next(line for line in report() if line.strip().startswith("Durra"))
    assert durra.split()[1:] == ["1/2", "0/0", "0/0"]  # train, validation, test
