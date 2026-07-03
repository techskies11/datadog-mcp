"""Unit tests for `datadog_mcp.tools.downtimes`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from datadog_mcp.auth import DatadogAuth
from datadog_mcp.tools.downtimes import (
    _get_downtime,
    _list_downtimes,
    _schedule_downtime,
    _update_downtime,
)


def _mock_downtime(**attrs: object) -> MagicMock:
    downtime = MagicMock()
    downtime.to_dict.return_value = {
        "id": "abc123",
        "type": "downtime",
        "attributes": {
            "scope": "env:staging",
            "message": "test downtime",
            "status": "scheduled",
            "monitor_identifier": {"monitor_id": 42},
            "schedule": {"start": "2024-01-01T00:00:00Z", "end": "2024-01-02T00:00:00Z"},
            "display_timezone": "UTC",
            "mute_first_recovery_notification": False,
            "canceled": None,
            "created": "2024-01-01T00:00:00Z",
            "modified": "2024-01-01T00:00:00Z",
            **attrs,
        },
    }
    return downtime


def test_schedule_downtime_success(fake_auth: DatadogAuth) -> None:
    with patch("datadog_mcp.tools.downtimes.DowntimesApi") as mock_api_cls:
        mock_api_cls.return_value.create_downtime.return_value = MagicMock(data=_mock_downtime())
        result = _schedule_downtime(
            "env:staging", "test downtime", 42, None, "now", "now+1h", None, False, fake_auth
        )

    assert result.success is True
    assert result.downtime is not None
    assert result.downtime.id == "abc123"
    assert result.downtime.monitor_id == 42
    assert result.downtime.scope == "env:staging"


def test_get_downtime_success(fake_auth: DatadogAuth) -> None:
    with patch("datadog_mcp.tools.downtimes.DowntimesApi") as mock_api_cls:
        mock_api_cls.return_value.get_downtime.return_value = MagicMock(data=_mock_downtime())
        result = _get_downtime("abc123", fake_auth)

    assert result.success is True
    assert result.downtime is not None
    assert result.downtime.status == "scheduled"


def test_list_downtimes_success(fake_auth: DatadogAuth) -> None:
    with patch("datadog_mcp.tools.downtimes.DowntimesApi") as mock_api_cls:
        mock_api_cls.return_value.list_downtimes.return_value = MagicMock(
            data=[_mock_downtime(), _mock_downtime(id="def456")]
        )
        result = _list_downtimes(True, 100, fake_auth)

    assert result.success is True
    assert result.count == 2


def test_update_downtime_end_now_preserves_existing_start(fake_auth: DatadogAuth) -> None:
    """Setting only `end` must not drop the existing `start`, and must not crash

    on the ISO-string-vs-datetime mismatch that `.to_dict()` round-tripping
    can introduce.
    """
    existing_schedule = MagicMock()
    existing_schedule.to_dict.return_value = {
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-02T00:00:00Z",
    }
    existing_attrs = MagicMock(schedule=existing_schedule)
    existing_response = MagicMock(data=MagicMock(attributes=existing_attrs))

    updated_downtime = _mock_downtime(message="ended early")
    updated_response = MagicMock(data=updated_downtime)

    with patch("datadog_mcp.tools.downtimes.DowntimesApi") as mock_api_cls:
        mock_api_cls.return_value.get_downtime.return_value = existing_response
        mock_api_cls.return_value.update_downtime.return_value = updated_response
        result = _update_downtime("abc123", None, "ended early", None, None, None, "now", fake_auth)

    assert result.success is True
    assert result.downtime is not None
    assert result.downtime.message == "ended early"


def test_downtime_error_maps_to_scope_hint(fake_auth: DatadogAuth) -> None:
    from datadog_api_client.exceptions import ForbiddenException

    with patch("datadog_mcp.tools.downtimes.DowntimesApi") as mock_api_cls:
        mock_api_cls.return_value.list_downtimes.side_effect = ForbiddenException(status=403)
        result = _list_downtimes(True, 100, fake_auth)

    assert result.success is False
    assert result.error is not None
    assert "monitors_downtime_write" in result.error
