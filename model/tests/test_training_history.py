"""Reading a run's per-epoch history, which `train --resume` continues from."""

import pytest

from sorghum_model.training_history import (
    best_validation_loss,
    finished_epoch_count,
    history_by_phase,
    read_history,
)

HEADER = "epoch,accuracy,loss,val_accuracy,val_loss\n"


def _write(tmp_path, text):
    path = tmp_path / "history.csv"
    path.write_text(HEADER + text, encoding="utf-8")
    return path


def test_no_file_means_nothing_finished(tmp_path):
    rows = read_history(tmp_path / "history.csv")
    assert rows == []
    assert finished_epoch_count(rows) == 0
    assert best_validation_loss(rows) is None


def test_counts_epochs_and_finds_the_best_validation_loss(tmp_path):
    rows = read_history(_write(tmp_path, "0,0.5,1.0,0.6,0.9\n1,0.6,0.8,0.7,0.7\n2,0.7,0.6,0.7,0.8\n"))
    assert finished_epoch_count(rows) == 3
    assert best_validation_loss(rows) == 0.7


def test_a_retrained_epoch_keeps_its_later_row(tmp_path):
    rows = read_history(_write(tmp_path, "0,0.5,1.0,0.6,0.9\n1,0.6,0.8,0.7,0.7\n1,0.6,0.8,0.7,0.65\n"))
    assert finished_epoch_count(rows) == 2
    assert rows[1]["val_loss"] == 0.65


def test_a_gap_in_the_epochs_is_refused(tmp_path):
    rows = read_history(_write(tmp_path, "0,0.5,1.0,0.6,0.9\n2,0.6,0.8,0.7,0.7\n"))
    with pytest.raises(ValueError, match="skips epochs"):
        finished_epoch_count(rows)


@pytest.mark.parametrize(("logged_epochs", "has_fine_tune"), [(1, False), (2, False), (3, True)])
def test_history_splits_at_the_head_phase_boundary(tmp_path, logged_epochs, has_fine_tune):
    lines = "".join(f"{epoch},0.5,1.0,0.6,{1 - epoch / 10}\n" for epoch in range(logged_epochs))
    head, fine_tune = history_by_phase(read_history(_write(tmp_path, lines)), head_epochs=2)
    assert len(head["val_loss"]) == min(logged_epochs, 2)
    assert (fine_tune is not None) is has_fine_tune
    if has_fine_tune:
        assert fine_tune["val_loss"] == [pytest.approx(0.8)]
