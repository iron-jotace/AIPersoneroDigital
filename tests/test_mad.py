from __future__ import annotations

from models.mad import mad_z_scores


def test_mad_z_scores_is_deterministic() -> None:
    values = [10, 12, 11, 13, 80]

    assert mad_z_scores(values) == mad_z_scores(values)


def test_identical_values_return_zero_scores() -> None:
    assert mad_z_scores([7, 7, 7, 7]) == [0.0, 0.0, 0.0, 0.0]


def test_clear_outlier_receives_higher_score_than_normal_values() -> None:
    scores = mad_z_scores([10, 11, 12, 13, 80])

    assert scores[-1] > max(scores[:-1])


def test_output_length_equals_input_length() -> None:
    values = [4, 5, 6, 7, 100]

    assert len(mad_z_scores(values)) == len(values)

