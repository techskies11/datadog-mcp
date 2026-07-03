"""Datadog MCP Server - main entry point.

Tool implementations live in `datadog_mcp.tools.*`, one module per Datadog
domain (logs, aggregations, metrics, apm, dashboards, monitors). Each module
exposes a `register_<domain>_tools(mcp)` function; this file's job is only
composition - wiring those domains plus resources and prompts onto a single
`FastMCP` instance.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastmcp import FastMCP

from datadog_mcp.auth import get_auth_instance
from datadog_mcp.tools.aggregations import register_aggregation_tools
from datadog_mcp.tools.apm import register_apm_tools
from datadog_mcp.tools.dashboards import register_dashboard_tools
from datadog_mcp.tools.downtimes import register_downtime_tools
from datadog_mcp.tools.logs import register_logs_tools
from datadog_mcp.tools.metrics import register_metrics_tools
from datadog_mcp.tools.monitors import list_monitors_summary, register_monitor_tools

mcp = FastMCP("Datadog Integration")

register_logs_tools(mcp)
register_aggregation_tools(mcp)
register_metrics_tools(mcp)
register_apm_tools(mcp)
register_dashboard_tools(mcp)
register_monitor_tools(mcp)
register_downtime_tools(mcp)


# ===== RESOURCES - Proactive Context =====


@mcp.resource("datadog://status")
def get_datadog_status() -> str:
    """Current Datadog account status: monitor alert counts and recent monitors.

    Use this when you need a quick health snapshot before deciding what to
    investigate further. This makes exactly one Datadog API call
    (list_monitors, capped at 10 results) to avoid burning rate limit budget
    on every read of this resource.
    """
    auth = get_auth_instance()
    monitors_result = list_monitors_summary(
        group_states=None,
        name=None,
        tags=None,
        monitor_tags=None,
        with_downtimes=False,
        limit=10,
        auth=auth,
    )

    if not monitors_result.success:
        return f"# Datadog Account Status\n\nCould not fetch monitors: {monitors_result.error}"

    alerting = [m.name for m in monitors_result.monitors if m.overall_state == "Alert"]

    return f"""# Datadog Account Status

## Monitors (sample of {monitors_result.count})
Currently alerting: {alerting or "none"}
Recent monitors: {[m.name for m in monitors_result.monitors[:5]]}

## Quick Actions
- Search logs: use `search_logs` with Datadog log query syntax
- Check metrics: use `query_metrics` with a metric name
- Browse dashboards: use `list_all_dashboards`
- Investigate an alert: use `get_monitor_details` then `search_logs`/`search_apm_traces`
"""


# ===== PROMPTS - Common Workflows =====


@mcp.prompt()
def investigate_errors(
    service: str | None = None, env: str = "prod", lookback: str = "now-1h"
) -> str:
    """Template for investigating error logs and traces in production.

    Use this when: user asks about errors, issues, or problems in production.

    Args:
        service: Optional service name to scope the investigation to
        env: Environment to search (default: "prod")
        lookback: How far back to look, as date math (default: "now-1h")
    """
    now = datetime.now(timezone.utc)
    service_filter = f" service:{service}" if service else ""

    return f"""I'll help you investigate errors{f" in {service}" if service else ""}. Here's what I'll do:

1. Search for error logs from {lookback} to now:
   Query: "status:error env:{env}{service_filter}"
   Use search_logs with from_time="{lookback}", to_time="now"

2. Count errors by type to find patterns:
   Use aggregate_logs_by_field grouped by an appropriate field (e.g. "error.kind", "@http.status_code")

3. Check for related APM traces with errors:
   Use search_apm_traces with query "env:{env}{service_filter} @error.message:*"

4. Look for any triggered monitors:
   Use list_all_monitors with group_states="alert"

Current time: {now.isoformat()}

Let me start searching for errors now..."""


@mcp.prompt()
def performance_analysis(service: str | None = None, lookback: str = "now-4h") -> str:
    """Template for analyzing system performance and latency issues.

    Use this when: user asks about performance, slowness, or latency.

    Args:
        service: Optional service name to focus the analysis on
        lookback: How far back to analyze, as date math (default: "now-4h")
    """
    scope = f" for {service}" if service else ""
    service_filter = f" service:{service}" if service else ""

    return f"""I'll analyze system performance{scope}. Here's my approach:

1. Query resource metrics from {lookback} to now:
   Use query_metrics for CPU ("avg:system.cpu.user{{*}}") and memory ("avg:system.mem.used{{*}}")

2. Find slow traces:
   Use search_apm_traces with query "{f"service:{service}" if service else "*"} @duration:>1000000000"
   (duration filter is in nanoseconds; 1000000000ns = 1s)

3. Get latency/error statistics without pulling raw spans:
   Use aggregate_spans with query "*{service_filter}" grouped by "resource_name"

4. Check for performance-related monitors:
   Use search_monitors with query "tag:performance{service_filter}"

Which service or metric would you like me to focus on first?"""


@mcp.prompt()
def triage_alerting_monitors(env: str | None = None) -> str:
    """Template for triaging monitors that are currently in an alert state.

    Use this when: user asks "what's alerting?", "what's broken right now?",
    or wants a prioritized look at active incidents.

    Args:
        env: Optional environment to scope the triage to (e.g. "prod")
    """
    scope_note = f' scoped to tags="env:{env}"' if env else ""
    tags_arg = f' tags="env:{env}"' if env else ""

    return f"""I'll triage currently-alerting monitors{scope_note}. Here's my approach:

1. List alerting monitors:
   Use list_all_monitors with group_states="alert"{tags_arg}

2. For each alerting monitor (highest priority first), get details:
   Use get_monitor_details to see the exact query and threshold that tripped

3. Correlate with recent changes:
   Use search_logs or search_apm_traces around the time it started alerting
   (check get_monitor_details' `overall_state` history/query for context)

4. Check if it's already being handled:
   Use list_downtimes to see if a downtime already covers this scope
   (if so, it may be expected/known maintenance, not a new incident)

I'll start by listing what's currently alerting..."""


@mcp.prompt()
def create_monitoring(target: str = "a service") -> str:
    """Template for guiding the user through setting up new monitors and dashboards.

    Use this when: user wants to create monitors, alerts, or dashboards.

    Args:
        target: What is being monitored, for context in the response (e.g. a service name)
    """
    return f"""I'll help you set up monitoring for {target}. I can create:

1. **Monitors/Alerts** (validate first with validate_monitor, then create_alert_monitor):
   - Metric alerts (CPU, memory, error rate thresholds)
   - Log alerts (error pattern rates)
   - APM alerts (latency, error rate)

2. **Dashboards** (see the `datadog://widget-templates` resource for widget examples):
   - System overview (timeseries + query_value widgets)
   - Service-specific metrics
   - Custom visualizations (toplist, heatmap, etc.)

What would you like to monitor, and what should trigger an alert?"""


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
