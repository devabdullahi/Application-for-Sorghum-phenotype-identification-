"""The per-epoch training history a run keeps on disk, so `train --resume` can continue it.

Keras' CSVLogger appends one row per finished epoch to `history.csv` in the run directory,
next to the weights of that epoch. A run that dies (on 2026-10-23 one stopped in epoch 19 of
20 and lost its report) is resumed from the last finished epoch. Kept free of TensorFlow so it
is unit-tested in the light environment.
"""

import csv
from pathlib import Path

HISTORY_FILE = "history.csv"

_EPOCH_COLUMN = "epoch"


def read_history(path: Path) -> list[dict[str, float]]:
    """Rows of a CSVLogger file in epoch order, one per epoch; empty when there is no file.

    An epoch can appear twice when a run died after logging it but before its weights were
    saved and then trained it again; the later row is the one that matches the weights, so
    it wins.
    """
    if not path.exists():
        return []
    by_epoch: dict[int, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            epoch = int(row[_EPOCH_COLUMN])
            by_epoch[epoch] = {
                name: float(value) for name, value in row.items() if name != _EPOCH_COLUMN
            } | {_EPOCH_COLUMN: epoch}
    return [by_epoch[epoch] for epoch in sorted(by_epoch)]


def finished_epoch_count(rows: list[dict[str, float]]) -> int:
    """Number of epochs finished so far, which is also the index of the next epoch.

    Epochs are numbered from 0 across both training phases, so the count is the highest
    logged epoch plus one. Raises ValueError when an epoch is missing, because the weights on
    disk would then not match the history.
    """
    epochs = [int(row[_EPOCH_COLUMN]) for row in rows]
    if epochs != list(range(len(epochs))):
        raise ValueError(f"training history skips epochs: logged {epochs}")
    return len(epochs)


def best_validation_loss(rows: list[dict[str, float]]) -> float | None:
    """Lowest validation loss logged so far, or None before the first epoch."""
    losses = [row["val_loss"] for row in rows if "val_loss" in row]
    return min(losses) if losses else None


def history_by_phase(
    rows: list[dict[str, float]], head_epochs: int
) -> tuple[dict[str, list[float]], dict[str, list[float]] | None]:
    """Splits the history into the head phase and the fine-tune phase (None if not reached).

    Each phase maps a metric name to its per-epoch values, the shape of Keras'
    `History.history`, so the training report looks the same as before resuming existed.
    """

    def columns(phase_rows: list[dict[str, float]]) -> dict[str, list[float]]:
        names = [name for name in phase_rows[0] if name != _EPOCH_COLUMN] if phase_rows else []
        return {name: [row[name] for row in phase_rows] for name in names}

    head_rows = [row for row in rows if row[_EPOCH_COLUMN] < head_epochs]
    fine_tune_rows = [row for row in rows if row[_EPOCH_COLUMN] >= head_epochs]
    return columns(head_rows), (columns(fine_tune_rows) if fine_tune_rows else None)
