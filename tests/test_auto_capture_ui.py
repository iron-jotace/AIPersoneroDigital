from __future__ import annotations

from ui.dashboard import (
    auto_capture_countdown_seconds,
    auto_capture_interval_elapsed,
    auto_capture_is_eligible,
    should_auto_capture_rerun,
)


def test_auto_capture_is_only_eligible_for_enabled_real_read_only() -> None:
    assert auto_capture_is_eligible("REAL_READ_ONLY", True)
    assert not auto_capture_is_eligible("MOCK", True)
    assert not auto_capture_is_eligible("REAL_READ_ONLY", False)


def test_auto_capture_interval_elapsed_when_no_previous_capture() -> None:
    assert auto_capture_interval_elapsed(now=1000.0, last_capture_ts=None, interval_seconds=300)


def test_auto_capture_interval_elapsed_after_interval() -> None:
    assert auto_capture_interval_elapsed(now=1300.0, last_capture_ts=1000.0, interval_seconds=300)
    assert not auto_capture_interval_elapsed(now=1299.0, last_capture_ts=1000.0, interval_seconds=300)


def test_auto_capture_countdown_seconds() -> None:
    assert auto_capture_countdown_seconds(now=1100.0, last_capture_ts=1000.0, interval_seconds=300) == 200
    assert auto_capture_countdown_seconds(now=1400.0, last_capture_ts=1000.0, interval_seconds=300) == 0
    assert auto_capture_countdown_seconds(now=1000.0, last_capture_ts=None, interval_seconds=300) == 0


def test_should_auto_capture_rerun_only_when_enabled_and_eligible() -> None:
    assert should_auto_capture_rerun(auto_capture_enabled=True, eligible=True)


def test_should_auto_capture_rerun_false_when_disabled() -> None:
    assert not should_auto_capture_rerun(auto_capture_enabled=False, eligible=True)


def test_should_auto_capture_rerun_false_when_not_eligible() -> None:
    assert not should_auto_capture_rerun(auto_capture_enabled=True, eligible=False)
