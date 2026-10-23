"""Verifies unreviewed Commons and Flickr labels with BioCLIP 2 zero-shot (`review-labels`).

Commons labels come from a category and Flickr labels from a text search, so they are stored
as `unreviewed` and kept out of training. BioCLIP 2 (Gu et al. 2025, imageomics/bioclip-2),
the model the research notes recommend for cleaning plant photos, scores each photo against
one text prompt per candidate label; probabilities are summed per species class.

- A plant row becomes verified when BioCLIP's top class is the row's class with at least
  `LabelReviewSettings.min_class_probability`.
- A `no_plant` row becomes verified when the summed probability of every plant class is
  below `max_plant_probability` ("bare soil", "wooden board", "human hand" win).

Rows that fail stay unreviewed, so they never train. Either way the verdict is appended to
`label_source` ("bioclip-2 agreement p=0.91"), which also marks the row as reviewed so a
re-run skips it. ASSUMPTION - confirm: a BioCLIP 2 agreement counts as label verification.

This module holds the decision only; the model runs in `bioclip_classifier.py`, so the rules
are tested without PyTorch.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from sorghum_model.manifest import ImageRecord, LabelStatus
from sorghum_model.settings import LabelReviewSettings
from sorghum_model.species_classes import SPECIES_CLASS_NAMES

REVIEW_MODEL_NAME = "bioclip-2"
NO_PLANT_CLASS = "no_plant"


@dataclass(frozen=True)
class ReviewPrompt:
    """One zero-shot candidate: the text BioCLIP scores and the class it stands for."""

    text: str
    class_name: str


# BioCLIP was trained on taxonomic names, so plant classes are prompted by scientific name.
# `other_plant` and the no-plant scenes are there so a photo of a weed, a field of soil or a
# hand has somewhere to go other than the row's class.
REVIEW_PROMPTS: tuple[ReviewPrompt, ...] = (
    ReviewPrompt("Sorghum bicolor", "sorghum_bicolor"),
    ReviewPrompt("Sorghum halepense", "johnson_grass"),
    ReviewPrompt("Zea mays", "maize"),
    ReviewPrompt("Saccharum officinarum", "sugarcane"),
    ReviewPrompt("Cenchrus americanus", "pearl_millet"),
    ReviewPrompt("Eleusine coracana", "finger_millet"),
    ReviewPrompt("Sorghastrum nutans", "other_grass"),
    ReviewPrompt("Andropogon gerardi", "other_grass"),
    ReviewPrompt("Schizachyrium scoparium", "other_grass"),
    ReviewPrompt("Bothriochloa ischaemum", "other_grass"),
    ReviewPrompt("Hyparrhenia hirta", "other_grass"),
    ReviewPrompt("Magnoliopsida, a broadleaf flowering plant", "other_plant"),
    ReviewPrompt("bare soil", NO_PLANT_CLASS),
    ReviewPrompt("cracked dry ground", NO_PLANT_CLASS),
    ReviewPrompt("wooden board", NO_PLANT_CLASS),
    ReviewPrompt("cardboard", NO_PLANT_CLASS),
    ReviewPrompt("human hand", NO_PLANT_CLASS),
)

# Takes image paths, returns one probability row per image over REVIEW_PROMPTS (rows sum to 1).
PromptClassifier = Callable[[Sequence[Path]], np.ndarray]


@dataclass(frozen=True)
class ReviewVerdict:
    """BioCLIP's reading of one photo against its label."""

    is_verified: bool
    top_class: str
    top_class_probability: float
    plant_probability: float


def class_probabilities(prompt_probabilities: np.ndarray) -> dict[str, float]:
    """Sums one image's prompt probabilities per species class."""
    totals = {name: 0.0 for name in SPECIES_CLASS_NAMES}
    for prompt, probability in zip(REVIEW_PROMPTS, prompt_probabilities, strict=True):
        totals[prompt.class_name] += float(probability)
    return totals


def judge(
    class_name: str, prompt_probabilities: np.ndarray, settings: LabelReviewSettings
) -> ReviewVerdict:
    """Decides whether BioCLIP's probabilities confirm `class_name`."""
    totals = class_probabilities(prompt_probabilities)
    top_class = max(totals, key=totals.get)
    plant_probability = sum(p for name, p in totals.items() if name != NO_PLANT_CLASS)
    if class_name == NO_PLANT_CLASS:
        is_verified = plant_probability < settings.max_plant_probability
    else:
        is_verified = top_class == class_name and totals[class_name] >= settings.min_class_probability
    return ReviewVerdict(is_verified, top_class, totals[top_class], plant_probability)


def is_reviewed(record: ImageRecord) -> bool:
    """Whether BioCLIP has already judged this row (its verdict is in the label source)."""
    return REVIEW_MODEL_NAME in record.label_source


def apply_verdict(record: ImageRecord, verdict: ReviewVerdict) -> ImageRecord:
    """The row with BioCLIP's verdict recorded; verified only when BioCLIP agrees."""
    if record.class_name == NO_PLANT_CLASS:
        detail = f"plant p={verdict.plant_probability:.2f}"
    else:
        detail = f"top {verdict.top_class} p={verdict.top_class_probability:.2f}"
    if verdict.is_verified:
        if record.class_name == NO_PLANT_CLASS:
            note = f"{REVIEW_MODEL_NAME} agreement no plant, {detail}"
        else:
            note = f"{REVIEW_MODEL_NAME} agreement p={verdict.top_class_probability:.2f}"
        status = LabelStatus.VERIFIED
    else:
        note = f"{REVIEW_MODEL_NAME} disagreement, {detail}"
        status = LabelStatus.UNREVIEWED
    return replace(record, label_source=f"{record.label_source}; {note}", label_status=status)


def _classify_batch(batch, records, data_root, classify):
    """(index, probabilities) for each readable image of the batch.

    One missing or corrupt file must not stop a review of thousands, so a failing batch is
    retried one image at a time and the unreadable rows are left unjudged (still unreviewed).
    """
    try:
        rows = classify([data_root / records[index].image_path for index in batch])
        return list(zip(batch, rows, strict=True))
    except OSError:
        judged = []
        for index in batch:
            try:
                judged.append((index, classify([data_root / records[index].image_path])[0]))
            except OSError as error:
                print(f"warning: skipped {records[index].image_path}: {error}")
        return judged


def review_records(
    records: list[ImageRecord],
    data_root: Path,
    classify: PromptClassifier,
    settings: LabelReviewSettings,
    on_checkpoint: Callable[[list[ImageRecord]], None] = lambda records: None,
) -> list[ImageRecord]:
    """Judges every unreviewed, not yet judged row; other rows are returned unchanged.

    `on_checkpoint` receives the whole updated list every `checkpoint_every_rows` judged rows,
    so the caller can save progress.
    """
    updated = list(records)
    pending = [
        index for index, record in enumerate(updated)
        if record.label_status is LabelStatus.UNREVIEWED and not is_reviewed(record)
    ]
    judged_since_checkpoint = 0
    for start in range(0, len(pending), settings.batch_size):
        batch = pending[start : start + settings.batch_size]
        for index, row in _classify_batch(batch, updated, data_root, classify):
            updated[index] = apply_verdict(updated[index], judge(updated[index].class_name, row, settings))
        judged_since_checkpoint += len(batch)
        if judged_since_checkpoint >= settings.checkpoint_every_rows:
            on_checkpoint(updated)
            judged_since_checkpoint = 0
    return updated
