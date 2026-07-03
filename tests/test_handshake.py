"""MCP handshake smoke test.

This is the safety net referenced by the plan: it proves the server can boot
and answer `list_tools`/`call_tool` over an in-memory MCP transport *before*
any teammate's `mcp.json` picks up a broken build. If this test fails, the
server would fail to start for the whole team.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client

from datadog_mcp.server import mcp

# Frozen list of tool names that existed before the v2 revamp. Per the plan's
# compatibility guarantee, none of these may be renamed or removed.
EXPECTED_BASELINE_TOOL_NAMES = {
    "search_logs",
    "count_logs",
    "count_unique_values",
    "aggregate_logs_by_field",
    "get_log_details",
    "query_metrics",
    "list_available_metrics",
    "send_custom_metric",
    "list_all_dashboards",
    "get_dashboard_details",
    "create_new_dashboard",
    "update_existing_dashboard",
    "search_apm_traces",
    "get_full_trace",
    "list_apm_services",
    "list_all_monitors",
    "get_monitor_details",
    "create_alert_monitor",
    "update_alert_monitor",
    "silence_monitor",
    "unsilence_monitor",
}


@pytest.mark.asyncio
async def test_server_initializes_and_lists_baseline_tools() -> None:
    """The server must boot with no credentials and expose every baseline tool."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}

    missing = EXPECTED_BASELINE_TOOL_NAMES - tool_names
    assert not missing, f"Baseline tools missing (renamed or removed?): {missing}"


@pytest.mark.asyncio
async def test_server_lists_resources_and_prompts() -> None:
    """Resources and prompts must still be registered after any refactor."""
    async with Client(mcp) as client:
        resources = await client.list_resources()
        prompts = await client.list_prompts()

    resource_uris = {str(r.uri) for r in resources}
    assert "datadog://status" in resource_uris

    prompt_names = {p.name for p in prompts}
    assert {"investigate_errors", "performance_analysis", "create_monitoring"} <= prompt_names


@pytest.mark.asyncio
async def test_call_tool_round_trip_with_mocked_datadog_api() -> None:
    """A tool call must round-trip through the MCP protocol end to end.

    The underlying Datadog LogsApi is mocked so this test needs neither
    credentials nor network access; it only proves the MCP plumbing
    (schema validation, dispatch, structured content) is intact.
    """
    mock_response = MagicMock()
    mock_response.data = []
    mock_response.meta = MagicMock()
    mock_response.meta.page = MagicMock()
    mock_response.meta.page.after = None

    with (
        patch.dict("os.environ", {"DD_API_KEY": "fake", "DD_APP_KEY": "fake"}),
        patch(
            "datadog_api_client.v2.api.logs_api.LogsApi.list_logs",
            return_value=mock_response,
        ),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "search_logs",
                {"query": "status:error", "from_time": "now-1h", "to_time": "now"},
            )

    assert result.is_error is False
    assert result.data is not None
