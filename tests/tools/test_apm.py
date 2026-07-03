"""Unit tests for `datadog_mcp.tools.apm`.

Specifically regression-tests `get_full_trace`: the original implementation
imported `datadog_api_client.v2.api.traces_api.TracesApi`, which does not
exist in `datadog-api-client` 2.57 (it was renamed/replaced by
`apm_trace_api.APMTraceApi`). Calling the tool would raise `ModuleNotFoundError`
at runtime - this test would have caught that.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from datadog_mcp.auth import DatadogAuth
from datadog_mcp.tools.apm import _get_trace


def _mock_span(**overrides: object) -> MagicMock:
    span = MagicMock()
    span.to_dict.return_value = {
        "span_id": 111,
        "trace_id": 999,
        "parent_id": None,
        "service": "api",
        "name": "web.request",
        "resource": "GET /foo",
        "type": "web",
        "start_time": 1_000_000,
        "end_time": 2_000_000,
        "duration": 1_000_000,
        "self_time": 500_000,
        "error": 0,
        "meta": {"env": "prod"},
        "metrics": {},
        **overrides,
    }
    return span


def test_get_trace_uses_apm_trace_api_get_trace_by_id(fake_auth: DatadogAuth) -> None:
    """`_get_trace` must call `APMTraceApi.get_trace_by_id`, not a nonexistent TracesApi."""
    root_span = _mock_span()
    child_span = _mock_span(span_id=222, parent_id=111, service="db", error=1)

    attributes = MagicMock(spans=[root_span, child_span], is_truncated=False)
    response = MagicMock(data=MagicMock(attributes=attributes))

    with patch(
        "datadog_api_client.v2.api.apm_trace_api.APMTraceApi.get_trace_by_id",
        return_value=response,
    ) as mock_get_trace:
        result = _get_trace("999", fake_auth)

    mock_get_trace.assert_called_once_with("999")
    assert result.success is True
    assert result.count == 2
    assert result.trace_id == "999"
    assert result.root_span is not None
    assert result.root_span.span_id == 111
    assert result.root_span.parent_id is None
    assert result.total_duration_ns == 1_000_000
    assert result.spans[1].is_error is True


def test_get_trace_not_found(fake_auth: DatadogAuth) -> None:
    """An empty span list is reported as a normal not-found result, not a crash."""
    attributes = MagicMock(spans=[], is_truncated=False)
    response = MagicMock(data=MagicMock(attributes=attributes))

    with patch(
        "datadog_api_client.v2.api.apm_trace_api.APMTraceApi.get_trace_by_id",
        return_value=response,
    ):
        result = _get_trace("does-not-exist", fake_auth)

    assert result.success is False
    assert result.error is not None
    assert "does-not-exist" in result.error
