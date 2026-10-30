"""External check of the species gate on MFWD, a dataset it never saw in training.

MFWD, the Moving Fields Weed Dataset (Genze et al. 2024, Sci Data 11:109,
https://doi.org/10.1038/s41597-024-02945-6, CC BY 4.0), has top-down greenhouse photos of
trays of young sorghum, maize and 28 weed species, with a box around every plant in `gt.csv`.
Its camera, light and growth stage differ from every training source, so it measures domain
shift. It is evaluation data only: no MFWD photo may enter a training split.

The flow is two steps, so the report can be rebuilt without running the model again:

1. `predict_trays` cuts a square crop around each plant box, runs the INT8 model the way the
   phone does, applies the app's decision rule (`decide_species`, a copy of `decideSpecies` in
   `shared/.../species/SpeciesGate.kt`) and writes one CSV row per crop. Needs TensorFlow.
2. `evaluation_report` reads those rows and scores them per crop, per plant (MFWD tracks one
   plant over many days), per growth stage, per box size and per EPPO code. Pure Python.
"""

import csv
import json
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image

from sorghum_model.calibration import softmax
from sorghum_model.preprocessing import square_and_resize
from sorghum_model.quantization import quantize_input
from sorghum_model.settings import MfwdEvaluationSettings, SpeciesDecisionSettings
from sorghum_model.species_classes import SpeciesGroup

# EPPO codes as MFWD writes them in `label_id`. Sorghum and maize carry one code per variety
# (MFWD's varieties.md); their `prepare_data.py` merges them into SORVU and ZEAMX the same way.
SORGHUM_CODES = frozenset({"SORVU", "SORFR", "SORHA", "SORKM", "SORKS", "SORRS", "SORSA"})
MAIZE_CODES = frozenset({"ZEAMX", "ZEAKJ", "ZEALP"})
# The grass weeds: narrow-leaved seedlings, the closest look-alikes to young sorghum.
GRASS_WEED_CODES = frozenset({"ECHCG", "AGRRE", "ALOMY", "POAAN"})
# MFWD's label for a weed its annotators could not name; it has no species, so it is skipped.
UNIDENTIFIED_WEED_CODE = "Weed"

# Box-size bins (long side in tray pixels) for the report; the lowest edge is the skip rule.
_BOX_SIZE_EDGES_PX = (128, 256, 512)

_CAPTURE_TIME = re.compile(r"_(\d{4})Y(\d{2})M(\d{2})D_(\d{2})H(\d{2})M(\d{2})S_")
_SECONDS_PER_DAY = 86400.0


class EppoGroup(Enum):
    """What a plant is, for scoring. Only SORGHUM should pass the gate."""

    SORGHUM = "sorghum"
    MAIZE = "maize"
    GRASS_WEED = "grassWeed"
    BROADLEAF_WEED = "broadleafWeed"


def eppo_group(code: str) -> EppoGroup | None:
    """The scoring group of an MFWD `label_id`; None for the unidentified "Weed" label."""
    if code == UNIDENTIFIED_WEED_CODE:
        return None
    if code in SORGHUM_CODES:
        return EppoGroup.SORGHUM
    if code in MAIZE_CODES:
        return EppoGroup.MAIZE
    if code in GRASS_WEED_CODES:
        return EppoGroup.GRASS_WEED
    # Every other MFWD species is a dicot weed (the class map lists no further grass).
    return EppoGroup.BROADLEAF_WEED


@dataclass(frozen=True)
class PlantBox:
    """One row of MFWD's `gt.csv`: a plant's box in one tray photo.

    Coordinates are pixels of the stored image (origin top-left); `x_max` and `y_max` are
    exclusive, as numpy slicing in MFWD's own `prepare_data.py` treats them. `image_name` is
    the `filename` column, e.g. "SORVU/121806/SORFR_121806_2021Y10M07D_18H57M39S_img".
    """

    track_id: int
    eppo_code: str
    bbox_id: int
    x_min: int
    y_min: int
    x_max: int
    y_max: int
    image_name: str
    tray_id: int

    @property
    def image_stem(self) -> str:
        """The photo's file name without folder or extension, as stored inside the tray zip."""
        return self.image_name.rsplit("/", 1)[-1]

    @property
    def long_side_px(self) -> int:
        return max(self.x_max - self.x_min, self.y_max - self.y_min)


def read_ground_truth(path: Path) -> list[PlantBox]:
    """Reads MFWD's `gt.csv`. Raises ValueError on a missing column or an empty box."""
    boxes = []
    with path.open(newline="") as file:
        for row in csv.DictReader(file):
            try:
                box = PlantBox(
                    track_id=int(row["track_id"]),
                    eppo_code=row["label_id"],
                    bbox_id=int(row["bbox_id"]),
                    x_min=int(row["xmin"]),
                    y_min=int(row["ymin"]),
                    x_max=int(row["xmax"]),
                    y_max=int(row["ymax"]),
                    image_name=row["filename"],
                    tray_id=int(row["tray_id"]),
                )
            except KeyError as error:
                raise ValueError(f"{path}: missing column {error}") from error
            if box.x_max <= box.x_min or box.y_max <= box.y_min:
                raise ValueError(f"{path}: empty box {box.bbox_id}")
            boxes.append(box)
    return boxes


def capture_time(image_stem: str) -> datetime:
    """When a tray photo was taken, read from its name ("..._2021Y10M07D_18H57M39S_img")."""
    match = _CAPTURE_TIME.search(image_stem)
    if match is None:
        raise ValueError(f"no capture time in image name {image_stem!r}")
    return datetime(*(int(part) for part in match.groups()))


def days_since_tray_start(boxes: Iterable[PlantBox]) -> dict[str, float]:
    """Days from each tray's first annotated photo to each photo, keyed by `image_name`.

    MFWD publishes no sowing date, so this is the growth-stage proxy: annotation starts once
    seedlings are visible, so day 0 is about emergence.
    """
    times = {box.image_name: (box.tray_id, capture_time(box.image_stem)) for box in boxes}
    tray_start: dict[int, datetime] = {}
    for tray_id, taken in times.values():
        if tray_id not in tray_start or taken < tray_start[tray_id]:
            tray_start[tray_id] = taken
    return {
        name: (taken - tray_start[tray_id]).total_seconds() / _SECONDS_PER_DAY
        for name, (tray_id, taken) in times.items()
    }


def photo_key(image_stem: str) -> str:
    """The part of a photo name that identifies it inside a tray zip: tray and capture time.

    `gt.csv` names a maize photo by its variety ("ZEALP_127801_2021Y08M03D_08H00M29S_img")
    while the zip names it by its folder ("ZEAMX_127801_..."), so the leading code is dropped.
    """
    code, separator, rest = image_stem.partition("_")
    if not separator or not code:
        raise ValueError(f"unexpected MFWD photo name {image_stem!r}")
    return rest


def square_crop_box(
    box: PlantBox, image_width_px: int, image_height_px: int, margin_fraction: float
) -> tuple[int, int, int, int]:
    """A square (left, top, right, bottom) around the box, with a margin, inside the image.

    The side is the box's long side plus `margin_fraction` of it on each side. The square is
    centred on the box, then shifted (not shrunk) to stay inside the image, so a plant at the
    tray edge keeps its whole box; only a square larger than the image is cut down. The model's
    centre-square crop then changes nothing.
    """
    side = round(box.long_side_px * (1 + 2 * margin_fraction))
    side = min(side, image_width_px, image_height_px)
    centre_x = (box.x_min + box.x_max) / 2
    centre_y = (box.y_min + box.y_max) / 2
    left = min(max(round(centre_x - side / 2), 0), image_width_px - side)
    top = min(max(round(centre_y - side / 2), 0), image_height_px - side)
    return left, top, left + side, top + side


class SpeciesOutcome(Enum):
    """What the app shows for a photo (the `SpeciesCheck` cases that come from the model)."""

    SORGHUM = "sorghum"
    NOT_SORGHUM = "notSorghum"
    UNSURE = "unsure"
    NO_PLANT = "noPlant"


@dataclass(frozen=True)
class SpeciesDecision:
    outcome: SpeciesOutcome
    sorghum_probability: float
    top_class: str
    top_probability: float
    named_look_alike: str | None


def decide_species(
    probabilities: Sequence[float],
    class_ids: Sequence[str],
    class_groups: Sequence[SpeciesGroup],
    sorghum_threshold: float,
    settings: SpeciesDecisionSettings,
) -> SpeciesDecision:
    """The app's decision, step for step as `decideSpecies` in `SpeciesGate.kt`.

    Sorghum first, against the calibrated threshold; then "no plant" or "not sorghum" only
    when confident; anything else is "unsure" (the app asks for a retake).
    """
    sorghum_probability = float(
        sum(p for p, group in zip(probabilities, class_groups) if group == SpeciesGroup.SORGHUM)
    )
    top_index = int(np.argmax(probabilities))
    top_class = class_ids[top_index]
    top_probability = float(probabilities[top_index])
    top_group = class_groups[top_index]

    def decision(outcome: SpeciesOutcome, named: str | None = None) -> SpeciesDecision:
        return SpeciesDecision(outcome, sorghum_probability, top_class, top_probability, named)

    if sorghum_probability >= sorghum_threshold:
        return decision(SpeciesOutcome.SORGHUM)
    if top_group == SpeciesGroup.NO_PLANT:
        if top_probability >= settings.min_no_plant_probability:
            return decision(SpeciesOutcome.NO_PLANT)
        return decision(SpeciesOutcome.UNSURE)
    if top_group == SpeciesGroup.SORGHUM:
        return decision(SpeciesOutcome.UNSURE)
    if 1 - sorghum_probability < settings.min_not_sorghum_probability:
        return decision(SpeciesOutcome.UNSURE)
    is_named = (
        top_group == SpeciesGroup.LOOK_ALIKE
        and top_probability >= settings.min_named_look_alike_probability
    )
    return decision(SpeciesOutcome.NOT_SORGHUM, top_class if is_named else None)


@dataclass(frozen=True)
class CropPrediction:
    """The model's answer for one plant crop: one row of the predictions CSV."""

    tray_id: int
    track_id: int
    bbox_id: int
    eppo_code: str
    image_stem: str
    days_since_tray_start: float
    box_long_side_px: int
    decision: SpeciesDecision

    @property
    def group(self) -> EppoGroup:
        group = eppo_group(self.eppo_code)
        if group is None:
            raise ValueError(f"crop {self.bbox_id} has no species ({self.eppo_code})")
        return group

    @property
    def is_called_sorghum(self) -> bool:
        return self.decision.outcome == SpeciesOutcome.SORGHUM


_PREDICTION_COLUMNS = (
    "tray_id", "track_id", "bbox_id", "eppo_code", "image_stem", "days_since_tray_start",
    "box_long_side_px", "outcome", "sorghum_probability", "top_class", "top_probability",
    "named_look_alike",
)


def write_predictions(predictions: Iterable[CropPrediction], path: Path) -> None:
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_PREDICTION_COLUMNS)
        for p in predictions:
            d = p.decision
            writer.writerow([
                p.tray_id, p.track_id, p.bbox_id, p.eppo_code, p.image_stem,
                f"{p.days_since_tray_start:.4f}", p.box_long_side_px, d.outcome.value,
                f"{d.sorghum_probability:.6f}", d.top_class, f"{d.top_probability:.6f}",
                d.named_look_alike or "",
            ])


def read_predictions(path: Path) -> list[CropPrediction]:
    with path.open(newline="") as file:
        return [
            CropPrediction(
                tray_id=int(row["tray_id"]),
                track_id=int(row["track_id"]),
                bbox_id=int(row["bbox_id"]),
                eppo_code=row["eppo_code"],
                image_stem=row["image_stem"],
                days_since_tray_start=float(row["days_since_tray_start"]),
                box_long_side_px=int(row["box_long_side_px"]),
                decision=SpeciesDecision(
                    outcome=SpeciesOutcome(row["outcome"]),
                    sorghum_probability=float(row["sorghum_probability"]),
                    top_class=row["top_class"],
                    top_probability=float(row["top_probability"]),
                    named_look_alike=row["named_look_alike"] or None,
                ),
            )
            for row in csv.DictReader(file)
        ]


def boxes_to_score(boxes: Iterable[PlantBox], settings: MfwdEvaluationSettings) -> list[PlantBox]:
    """Boxes with a named species and a long side of at least `min_box_side_px`."""
    return [
        box for box in boxes
        if eppo_group(box.eppo_code) is not None and box.long_side_px >= settings.min_box_side_px
    ]


def predict_trays(
    ground_truth: Path,
    jpegs_dir: Path,
    model_dir: Path,
    model_version: int,
    output_csv: Path,
    settings: MfwdEvaluationSettings,
    decision_settings: SpeciesDecisionSettings,
    threads: int,
) -> int:
    """Scores every box in the tray zips present under `jpegs_dir/<folder>/<tray>.zip`.

    Trays not downloaded are skipped, so a partial download gives a partial (still valid)
    evaluation; so are boxes whose photo is missing from its zip, with a warning. Returns the
    number of crops written. Needs TensorFlow.
    """
    import tensorflow as tf

    metadata = json.loads((model_dir / f"traits-v{model_version}.json").read_text())
    species = metadata["heads"]["species"]
    class_ids = [c["id"] for c in species["classes"]]
    class_groups = [SpeciesGroup(c["group"]) for c in species["classes"]]
    size_px = metadata["input"]["widthPx"]
    scale = metadata["input"]["quantization"]["scale"]
    zero_point = metadata["input"]["quantization"]["zeroPoint"]

    interpreter = tf.lite.Interpreter(
        model_path=str(model_dir / metadata["modelFile"]), num_threads=threads
    )
    interpreter.allocate_tensors()
    input_index = interpreter.get_input_details()[0]["index"]
    output_index = interpreter.get_output_details()[species["outputIndex"]]["index"]

    all_boxes = read_ground_truth(ground_truth)
    days = days_since_tray_start(all_boxes)
    boxes_by_zip: dict[Path, list[PlantBox]] = defaultdict(list)
    for box in boxes_to_score(all_boxes, settings):
        folder = box.image_name.split("/", 1)[0]
        boxes_by_zip[jpegs_dir / folder / f"{box.tray_id}.zip"].append(box)

    predictions = []
    skipped_boxes = 0
    for zip_path in sorted(boxes_by_zip):
        if not zip_path.is_file():
            continue
        boxes_by_image: dict[str, list[PlantBox]] = defaultdict(list)
        for box in boxes_by_zip[zip_path]:
            boxes_by_image[box.image_stem].append(box)
        with zipfile.ZipFile(zip_path) as archive:
            members = {
                photo_key(Path(name).stem): name for name in archive.namelist() if not name.endswith("/")
            }
            for stem, image_boxes in sorted(boxes_by_image.items()):
                member = members.get(photo_key(stem))
                if member is None:
                    print(f"warning: {zip_path} has no photo {stem}; skipped its "
                          f"{len(image_boxes)} boxes", flush=True)
                    skipped_boxes += len(image_boxes)
                    continue
                with archive.open(member) as file, Image.open(file) as image:
                    tray_photo = image.convert("RGB")
                for box in image_boxes:
                    crop = tray_photo.crop(square_crop_box(
                        box, tray_photo.width, tray_photo.height, settings.crop_margin_fraction
                    ))
                    pixels = square_and_resize(crop, size_px)
                    interpreter.set_tensor(
                        input_index, quantize_input(pixels, scale, zero_point)[np.newaxis]
                    )
                    interpreter.invoke()
                    logits = interpreter.get_tensor(output_index)[0].astype(np.float64)
                    probabilities = softmax(logits[np.newaxis], species["temperature"])[0]
                    predictions.append(CropPrediction(
                        tray_id=box.tray_id,
                        track_id=box.track_id,
                        bbox_id=box.bbox_id,
                        eppo_code=box.eppo_code,
                        image_stem=stem,
                        days_since_tray_start=days[box.image_name],
                        box_long_side_px=box.long_side_px,
                        decision=decide_species(
                            probabilities, class_ids, class_groups,
                            species["sorghumThreshold"], decision_settings,
                        ),
                    ))
        print(f"{zip_path.parent.name}/{zip_path.name}: {len(predictions)} crops so far", flush=True)
    write_predictions(predictions, output_csv)
    if skipped_boxes:
        print(f"warning: {skipped_boxes} boxes skipped because their photo is not in the zip")
    return len(predictions)


def sorghum_vs_not(called_sorghum: Sequence[bool], is_sorghum: Sequence[bool]) -> dict:
    """Accuracy, precision and recall of "sorghum" against the truth, plus the counts."""
    true_positive = sum(c and t for c, t in zip(called_sorghum, is_sorghum))
    false_positive = sum(c and not t for c, t in zip(called_sorghum, is_sorghum))
    false_negative = sum(t and not c for c, t in zip(called_sorghum, is_sorghum))
    total = len(is_sorghum)
    correct = total - false_positive - false_negative
    return {
        "photos": total,
        "accuracy": _ratio(correct, total),
        "precision": _ratio(true_positive, true_positive + false_positive),
        "recall": _ratio(true_positive, true_positive + false_negative),
        "truePositive": true_positive,
        "falsePositive": false_positive,
        "falseNegative": false_negative,
    }


def plant_calls(predictions: Iterable[CropPrediction]) -> dict[int, tuple[str, bool, float]]:
    """Per plant (track): its EPPO code, whether it is called sorghum, and its sorghum share.

    A plant is called sorghum when more than half of its crops are, the answer a user would
    get from most photos of that plant.
    """
    crops: dict[int, list[CropPrediction]] = defaultdict(list)
    for p in predictions:
        crops[p.track_id].append(p)
    calls = {}
    for track_id, track in crops.items():
        codes = {p.eppo_code for p in track}
        if len(codes) != 1:
            raise ValueError(f"track {track_id} has several species: {sorted(codes)}")
        share = sum(p.is_called_sorghum for p in track) / len(track)
        calls[track_id] = (codes.pop(), share > 0.5, share)
    return calls


def stage_bin(days: float, settings: MfwdEvaluationSettings) -> str:
    """The growth-stage bin label of a crop, e.g. "7-13 d"."""
    start = int(days // settings.stage_bin_days) * settings.stage_bin_days
    return f"{start}-{start + settings.stage_bin_days - 1} d"


def box_size_bin(long_side_px: int, settings: MfwdEvaluationSettings) -> str:
    edges = (settings.min_box_side_px, *(e for e in _BOX_SIZE_EDGES_PX if e > settings.min_box_side_px))
    for low, high in zip(edges, edges[1:]):
        if low <= long_side_px < high:
            return f"{low}-{high - 1} px"
    return f">={edges[-1]} px"


def evaluation_report(predictions: Sequence[CropPrediction], settings: MfwdEvaluationSettings) -> dict:
    """Scores crops and plants; see the module docstring. Rates are "called sorghum" shares."""
    if not predictions:
        raise ValueError("no predictions to score")
    plants = plant_calls(predictions)

    def outcome_shares(rows: Sequence[CropPrediction]) -> dict:
        counts = Counter(p.decision.outcome.value for p in rows)
        return {outcome.value: _ratio(counts[outcome.value], len(rows)) for outcome in SpeciesOutcome}

    def summary(rows: Sequence[CropPrediction]) -> dict:
        # Plant calls from these rows only: in a growth-stage bin, a plant is judged on its
        # photos at that stage, not on its whole life.
        row_plants = plant_calls(rows)
        return {
            "photos": len(rows),
            "plants": len(row_plants),
            "calledSorghumRate": _ratio(sum(p.is_called_sorghum for p in rows), len(rows)),
            "plantsCalledSorghumRate": _ratio(
                sum(called for _, called, _ in row_plants.values()), len(row_plants)
            ),
            "outcomes": outcome_shares(rows),
        }

    def grouped(key) -> dict[str, list[CropPrediction]]:
        groups: dict[str, list[CropPrediction]] = defaultdict(list)
        for p in predictions:
            groups[key(p)].append(p)
        return dict(sorted(groups.items()))

    by_group = grouped(lambda p: p.group.value)
    per_eppo = {}
    for code, rows in grouped(lambda p: p.eppo_code).items():
        per_eppo[code] = {
            "group": rows[0].group.value,
            **summary(rows),
            "topClasses": dict(Counter(p.decision.top_class for p in rows).most_common()),
        }
    return {
        "settings": {
            "cropMarginFraction": settings.crop_margin_fraction,
            "minBoxSidePx": settings.min_box_side_px,
            "stageBinDays": settings.stage_bin_days,
        },
        "trays": len({p.tray_id for p in predictions}),
        "perPhoto": sorghum_vs_not(
            [p.is_called_sorghum for p in predictions],
            [p.group == EppoGroup.SORGHUM for p in predictions],
        ),
        "perPlant": sorghum_vs_not(
            [called for _, called, _ in plants.values()],
            [eppo_group(code) == EppoGroup.SORGHUM for code, _, _ in plants.values()],
        ),
        "perGroup": {name: summary(rows) for name, rows in by_group.items()},
        "perEppoCode": per_eppo,
        "perStage": {
            name: {bin_: summary(bin_rows) for bin_, bin_rows in _sorted_bins(
                rows, lambda p: stage_bin(p.days_since_tray_start, settings)
            ).items()}
            for name, rows in by_group.items()
        },
        "perBoxSize": {
            name: {bin_: summary(bin_rows) for bin_, bin_rows in _sorted_bins(
                rows, lambda p: box_size_bin(p.box_long_side_px, settings)
            ).items()}
            for name, rows in by_group.items()
        },
    }


def format_report(report: dict) -> str:
    """A plain-text view of `evaluation_report` for logs and the README."""
    lines = [f"MFWD external check: {report['trays']} trays"]
    for level in ("perPhoto", "perPlant"):
        m = report[level]
        lines.append(
            f"{level}: n={m['photos']} accuracy={m['accuracy']:.3f} precision={m['precision']:.3f} "
            f"recall={m['recall']:.3f} (TP {m['truePositive']}, FP {m['falsePositive']}, "
            f"FN {m['falseNegative']})"
        )
    lines.append("group: photos plants called-sorghum(photo) called-sorghum(plant) | outcomes")
    for name, s in report["perGroup"].items():
        lines.append(f"  {name}: {_summary_line(s)}")
    lines.append("EPPO code: photos plants called-sorghum(photo) (plant) | outcomes | top classes")
    for code, s in report["perEppoCode"].items():
        top = ", ".join(f"{k} {v}" for k, v in list(s["topClasses"].items())[:3])
        lines.append(f"  {code} ({s['group']}): {_summary_line(s)} | {top}")
    for section in ("perStage", "perBoxSize"):
        lines.append(f"{section}: photos plants called-sorghum(photo) (plant)")
        for name, bins in report[section].items():
            for bin_, s in bins.items():
                lines.append(
                    f"  {name} {bin_}: {s['photos']} {s['plants']} "
                    f"{s['calledSorghumRate']:.3f} {s['plantsCalledSorghumRate']:.3f}"
                )
    return "\n".join(lines)


def _summary_line(s: dict) -> str:
    outcomes = " ".join(f"{k} {v:.2f}" for k, v in s["outcomes"].items())
    return (
        f"{s['photos']} {s['plants']} {s['calledSorghumRate']:.3f} "
        f"{s['plantsCalledSorghumRate']:.3f} | {outcomes}"
    )


def _sorted_bins(rows: Sequence[CropPrediction], key) -> dict[str, list[CropPrediction]]:
    bins: dict[str, list[CropPrediction]] = defaultdict(list)
    for p in rows:
        bins[key(p)].append(p)
    # Bin labels start with their lower edge ("7-13 d", ">=512 px"); sort by it numerically.
    return dict(sorted(bins.items(), key=lambda item: int(re.search(r"\d+", item[0]).group())))


def _ratio(numerator: float, denominator: float) -> float:
    # An empty bin has no rate; NaN keeps it visible instead of reading as 0 or 1.
    return numerator / denominator if denominator else float("nan")
