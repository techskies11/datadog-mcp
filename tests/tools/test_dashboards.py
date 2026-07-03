"""Unit tests for `datadog_mcp.tools.dashboards`, focused on widget pre-validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from datadog_mcp.auth import DatadogAuth
from datadog_mcp.tools.dashboards import _create_dashboard, _validate_known_widgets


def test_valid_known_widget_types_pass() -> None:
    widgets = [
        {"definition": {"type": "timeseries", "requests": [{"q": "avg:system.cpu.user{*}"}]}},
        {"definition": {"type": "query_value", "requests": [{"q": "sum:requests.count{*}"}]}},
        {
            "definition": {
                "type": "toplist",
                "requests": [{"q": "top(sum:requests{*} by {service}, 5)"}],
            }
        },
    ]
    assert _validate_known_widgets(widgets) is None


def test_unmodeled_widget_types_pass_through_unvalidated() -> None:
    """Widget types this server doesn't model must not be rejected client-side."""
    widgets = [{"definition": {"type": "note", "content": "hello"}}]
    assert _validate_known_widgets(widgets) is None


def test_missing_requests_is_rejected() -> None:
    widgets = [{"definition": {"type": "timeseries", "requests": []}}]
    error = _validate_known_widgets(widgets)
    assert error is not None
    assert "Widget #0" in error
    assert "timeseries" in error


def test_missing_query_field_is_rejected() -> None:
    widgets = [{"definition": {"type": "query_value", "requests": [{"aggregator": "sum"}]}}]
    error = _validate_known_widgets(widgets)
    assert error is not None
    assert "query_value" in error


def test_create_dashboard_rejects_invalid_widget_before_api_call(fake_auth: DatadogAuth) -> None:
    """An invalid known-type widget must fail fast without calling the Datadog API."""
    widgets = [{"definition": {"type": "toplist", "requests": []}}]

    with patch("datadog_mcp.tools.dashboards.DashboardsApi") as mock_api_cls:
        result = _create_dashboard("Test", "ordered", widgets, None, None, None, None, fake_auth)

    mock_api_cls.return_value.create_dashboard.assert_not_called()
    assert result.success is False
    assert result.error is not None
    assert "toplist" in result.error


def test_create_dashboard_allows_unmodeled_widget_types(fake_auth: DatadogAuth) -> None:
    widgets = [{"definition": {"type": "group", "widgets": []}}]

    mock_response = MagicMock(id="abc", url="https://x/abc", title="Test")
    with patch("datadog_mcp.tools.dashboards.DashboardsApi") as mock_api_cls:
        mock_api_cls.return_value.create_dashboard.return_value = mock_response
        result = _create_dashboard("Test", "ordered", widgets, None, None, None, None, fake_auth)

    mock_api_cls.return_value.create_dashboard.assert_called_once()
    assert result.success is True
    assert result.dashboard_id == "abc"
