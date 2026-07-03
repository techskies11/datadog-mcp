"""Unit tests for the shared flexible time-value parser."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from datadog_mcp.utils.time import parse_time_value

FIXED_NOW = datetime(2024, 1, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_int_passes_through_unchanged() -> None:
    assert parse_time_value(1_700_000_000) == 1_700_000_000


def test_now_resolves_to_reference_time() -> None:
    assert parse_time_value("now", now=FIXED_NOW) == int(FIXED_NOW.timestamp())


@pytest.mark.parametrize(
    "expression,expected_delta_seconds",
    [
        ("now-1h", 3600),
        ("now-15m", 15 * 60),
        ("now-7d", 7 * 86400),
        ("now-30s", 30),
        ("now-2w", 2 * 604800),
    ],
)
def test_relative_date_math(expression: str, expected_delta_seconds: int) -> None:
    result = parse_time_value(expression, now=FIXED_NOW)
    assert result == int(FIXED_NOW.timestamp()) - expected_delta_seconds


@pytest.mark.parametrize(
    "expression,expected_delta_seconds",
    [
        ("now+1h", 3600),
        ("now+15m", 15 * 60),
        ("now+2d", 2 * 86400),
    ],
)
def test_future_relative_date_math(expression: str, expected_delta_seconds: int) -> None:
    result = parse_time_value(expression, now=FIXED_NOW)
    assert result == int(FIXED_NOW.timestamp()) + expected_delta_seconds


def test_numeric_string_seconds() -> None:
    assert parse_time_value("1700000000") == 1_700_000_000


def test_numeric_string_milliseconds() -> None:
    assert parse_time_value("1700000000000") == 1_700_000_000


def test_iso8601_with_z_suffix() -> None:
    result = parse_time_value("2024-01-28T10:00:00Z")
    expected = int(datetime(2024, 1, 28, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    assert result == expected


def test_iso8601_with_explicit_offset() -> None:
    result = parse_time_value("2024-01-28T10:00:00+00:00")
    expected = int(datetime(2024, 1, 28, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    assert result == expected


def test_invalid_value_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Could not parse time value"):
        parse_time_value("not-a-time")
