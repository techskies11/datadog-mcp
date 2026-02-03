"""Datadog MCP Server - Main entry point using FastMCP."""

from datetime import datetime, timedelta
from typing import Literal, cast

from fastmcp import FastMCP

from datadog_mcp.auth import DatadogAuth
from datadog_mcp.tools.aggregations import aggregate_logs as _aggregate_logs
from datadog_mcp.tools.aggregations import count_logs as _count_logs
from datadog_mcp.tools.aggregations import count_unique as _count_unique
from datadog_mcp.tools.apm import get_trace as _get_trace
from datadog_mcp.tools.apm import list_services as _list_services
from datadog_mcp.tools.apm import search_spans as _search_spans
from datadog_mcp.tools.dashboards import create_dashboard as _create_dashboard
from datadog_mcp.tools.dashboards import delete_dashboard as _delete_dashboard
from datadog_mcp.tools.dashboards import get_dashboard as _get_dashboard
from datadog_mcp.tools.dashboards import list_dashboards as _list_dashboards
from datadog_mcp.tools.dashboards import update_dashboard as _update_dashboard
from datadog_mcp.tools.logs import get_log_details as _get_log_details
from datadog_mcp.tools.logs import search_logs as _search_logs
from datadog_mcp.tools.metrics import list_metrics as _list_metrics
from datadog_mcp.tools.metrics import query_metrics as _query_metrics
from datadog_mcp.tools.metrics import submit_metrics as _submit_metrics
from datadog_mcp.tools.monitors import create_monitor as _create_monitor
from datadog_mcp.tools.monitors import delete_monitor as _delete_monitor
from datadog_mcp.tools.monitors import get_monitor as _get_monitor
from datadog_mcp.tools.monitors import list_monitors as _list_monitors
from datadog_mcp.tools.monitors import mute_monitor as _mute_monitor
from datadog_mcp.tools.monitors import unmute_monitor as _unmute_monitor
from datadog_mcp.tools.monitors import update_monitor as _update_monitor

# Create FastMCP instance with description
mcp = FastMCP("Datadog Integration")

# Global auth instance (initialized once at startup)
# Credentials come from environment variables set by Cursor
_auth_instance: DatadogAuth | None = None


def get_auth_instance() -> DatadogAuth:
    """Get or create the DatadogAuth instance.

    Credentials are loaded from environment variables:
    - DD_API_KEY: Datadog API key
    - DD_APP_KEY: Datadog Application key
    - DD_SITE: Datadog site (default: datadoghq.com)

    These should be set in Cursor's mcp.json, NOT in this project's .env
    """
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = DatadogAuth()
    return _auth_instance


# ===== RESOURCES - Proactive Context =====


@mcp.resource("datadog://status")
def get_datadog_status() -> str:
    """Current Datadog account status and recent activity.

    Provides context about active monitors, recent dashboards, and system health.
    Use this when you need to understand the current state before taking action.
    """
    auth = get_auth_instance()

    # Get quick snapshot
    monitors_result = _list_monitors(limit=10, auth=auth)
    dashboards_result = _list_dashboards(limit=5, auth=auth)

    status = f"""# Datadog Account Status

## Active Monitors
Total monitors: {monitors_result.get('count', 0)}
Recent monitors: {[m['name'] for m in monitors_result.get('monitors', [])[:3]]}

## Dashboards
Total dashboards: {dashboards_result.get('count', 0)}
Recent dashboards: {[d['title'] for d in dashboards_result.get('dashboards', [])[:3]]}

## Quick Actions
- Search logs: Use 'search_logs' with query syntax
- Check metrics: Use 'query_metrics' with metric name
- View dashboards: Use 'list_dashboards' to browse
"""
    return status


# ===== PROMPTS - Common Queries =====


@mcp.prompt()
def investigate_errors() -> str:
    """Template for investigating error logs in production.

    Use this when: User asks about errors, issues, or problems in production.
    """
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)

    return f"""I'll help you investigate errors. Here's what I'll do:

1. Search for error logs in the last hour:
   Query: "status:error env:prod"
   Time: {hour_ago.isoformat()}Z to {now.isoformat()}Z

2. Check for related APM traces with errors

3. Look for any triggered monitors

Let me search for errors now..."""


@mcp.prompt()
def performance_analysis() -> str:
    """Template for analyzing system performance issues.

    Use this when: User asks about performance, slowness, or latency.
    """
    return """I'll analyze system performance. Here's my approach:

1. Query CPU and memory metrics for the last 4 hours
2. Search for slow APM traces (>1s duration)
3. Check for performance-related monitors
4. Look at dashboard trends

Which service or metric would you like me to focus on?"""


@mcp.prompt()
def create_monitoring() -> str:
    """Template for setting up new monitoring.

    Use this when: User wants to create monitors, alerts, or dashboards.
    """
    return """I'll help you set up monitoring. I can create:

1. **Monitors/Alerts**:
   - Metric alerts (CPU, memory, errors)
   - Log alerts (error patterns)
   - APM alerts (latency, errors)

2. **Dashboards**:
   - System overview
   - Service-specific metrics
   - Custom visualizations

What would you like to monitor?"""


# ===== LOGS TOOLS =====


@mcp.tool()
def search_logs(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int = 25,
    cursor: str | None = None,
    sort: str = "timestamp",
    indexes: list[str] | None = None,
) -> dict:
    """Search and VIEW log entries. Returns paginated results.

    ⚠️ IMPORTANT: Use this ONLY when you need to VIEW log content for debugging.
    For COUNTING logs or unique values, use count_logs or count_unique instead.

    Use this when:
    - Need to view actual log messages and details
    - Debugging specific issues
    - Investigating error details

    DO NOT use for:
    - Counting logs (use count_logs)
    - Counting unique sessions/users (use count_unique)
    - Statistical analysis (use aggregate_logs)

    Args:
        query: Search query (e.g., "status:error service:api env:prod")
        from_time: Start time - ISO 8601, date math like "now-1h", or timestamp ms
        to_time: End time - ISO 8601, date math like "now", or timestamp ms
        page_size: Logs per page (default: 25, max: 50)
        cursor: Pagination cursor from previous response
        sort: "timestamp" or "-timestamp" for descending
        indexes: Optional list of index names

    Returns:
        Paginated logs with next_cursor for fetching more pages

    Examples:
        search_logs("status:error", "now-1h", "now")
        search_logs("service:api", "2024-01-28T10:00:00Z", "2024-01-28T11:00:00Z", page_size=50)
    """
    return _search_logs(
        query, from_time, to_time, page_size, cursor, sort, indexes, auth=get_auth_instance()
    )


@mcp.tool()
def count_logs(query: str, from_time: str, to_time: str, indexes: list[str] | None = None) -> dict:
    """Count logs matching a query WITHOUT fetching all data (fast & lightweight).

    ✅ PREFERRED for counting events - much faster than search_logs.

    Use this when:
    - "How many errors happened?"
    - "Count logs for a service"
    - Need a number, not log content

    DO NOT use search_logs just to count results - this is 10x faster.

    Args:
        query: Search query (e.g., "status:error service:api")
        from_time: Start time - ISO 8601, date math like "now-1h", or timestamp ms
        to_time: End time - ISO 8601, date math like "now", or timestamp ms
        indexes: Optional list of index names

    Returns:
        {"success": true, "count": 1234, "query": "..."}

    Examples:
        count_logs("status:error", "now-1h", "now")
        -> Returns: {"count": 45}
    """
    return _count_logs(query, from_time, to_time, indexes, auth=get_auth_instance())


@mcp.tool()
def count_unique_values(
    query: str, from_time: str, to_time: str, field: str, indexes: list[str] | None = None
) -> dict:
    """Count UNIQUE values of a field (distinct count / cardinality).

    ✅ PERFECT for counting unique sessions, users, IPs, etc.
    Much more efficient than fetching all logs and counting locally.

    Use this when:
    - "How many unique users/sessions?"
    - "Count distinct values"
    - "How many different X?"

    Args:
        query: Search query to filter logs
        from_time: Start time - ISO 8601, date math like "now-1h", or timestamp ms
        to_time: End time - ISO 8601, date math like "now", or timestamp ms
        field: Field to count unique values (e.g., "@session_id", "@user.id", "host")
        indexes: Optional list of index names

    Returns:
        {"success": true, "unique_count": 150, "field": "@session_id"}

    Examples:
        count_unique_values("service:omni-channel @airline_name:aeromexico", "now-1d", "now", "@session_id")
        -> Returns: {"unique_count": 150}
    """
    return _count_unique(query, from_time, to_time, field, indexes, auth=get_auth_instance())


@mcp.tool()
def aggregate_logs_by_field(
    query: str,
    from_time: str,
    to_time: str,
    group_by: str,
    aggregation: str = "count",
    metric: str | None = None,
    limit: int = 10,
    indexes: list[str] | None = None,
) -> dict:
    """Aggregate and group logs by a field with statistics (fast, no raw data transfer).

    ✅ PERFECT for analytics, charts, and dashboards.

    Use this when:
    - "Group errors by service"
    - "Top 10 airlines by conversation count"
    - "Average duration per endpoint"

    Args:
        query: Search query to filter logs
        from_time: Start time - ISO 8601, date math like "now-1h", or timestamp ms
        to_time: End time - ISO 8601, date math like "now", or timestamp ms
        group_by: Field to group by (e.g., "@airline_name", "service", "status")
        aggregation: Function - count, cardinality, pc75, pc90, pc95, pc99, sum, min, max, avg
        metric: Metric field for aggregations other than count (e.g., "@duration")
        limit: Max groups to return (default: 10)
        indexes: Optional list of index names

    Returns:
        {"success": true, "buckets": [{"key": "aeromexico", "count": 50}, ...]}

    Examples:
        aggregate_logs_by_field("service:api", "now-1d", "now", "status", "count")
        -> Returns top statuses with counts
    """
    return _aggregate_logs(
        query,
        from_time,
        to_time,
        group_by,
        cast(
            Literal[
                "count", "cardinality", "pc75", "pc90", "pc95", "pc99", "sum", "min", "max", "avg"
            ],
            aggregation,
        ),
        metric,
        limit,
        indexes,
        auth=get_auth_instance(),
    )


@mcp.tool()
def get_log_details(log_id: str) -> dict:
    """Get complete details of a specific log entry.

    Use this when: Need full information about a particular log (after searching).

    Args:
        log_id: Unique log identifier from search results

    Returns:
        dict with complete log data including all attributes
    """
    auth = get_auth_instance()
    return _get_log_details(log_id, auth=auth)


# ===== METRICS TOOLS =====


@mcp.tool()
def query_metrics(query: str, from_time: int, to_time: int) -> dict:
    """Query and visualize time series metrics.

    Use this when: Need to check system performance, resource usage, or custom metrics.

    Common queries:
    - CPU: "avg:system.cpu.user{*}"
    - Memory: "avg:system.mem.used{*}"
    - By host: "avg:system.load.1{host:web-01}"
    - By tag: "sum:requests.count{env:prod}"

    Args:
        query: Metric query in Datadog syntax (examples above)
        from_time: Start time as Unix timestamp (seconds)
        to_time: End time as Unix timestamp (seconds)

    Returns:
        dict with time series data points
    """
    auth = get_auth_instance()
    return _query_metrics(query, from_time, to_time, auth=auth)


@mcp.tool()
def list_available_metrics(filter: str | None = None, limit: int = 100) -> dict:
    """List all metrics available in Datadog.

    Use this when: Don't know exact metric name or want to discover what's available.

    Args:
        filter: Search term (e.g., 'cpu', 'memory', 'docker')
        limit: Max metrics to return (default: 100)

    Returns:
        dict with array of metric names
    """
    auth = get_auth_instance()
    return _list_metrics(filter, limit, auth=auth)


@mcp.tool()
def send_custom_metric(
    metric_name: str,
    points: list[tuple[int, float]],
    metric_type: str = "gauge",
    tags: list[str] | None = None,
    host: str | None = None,
    interval: int | None = None,
) -> dict:
    """Send custom metric data points to Datadog.

    Use this when: Need to track custom application metrics or business KPIs.

    Metric types:
    - gauge: Point-in-time value (temperature, queue size)
    - count: Count of events in interval
    - rate: Events per second

    Args:
        metric_name: Your metric name (e.g., 'app.users.active')
        points: [[timestamp, value], ...] where timestamp is Unix seconds
        metric_type: 'gauge', 'count', or 'rate'
        tags: Optional tags (e.g., ['env:prod', 'region:us'])
        host: Optional hostname
        interval: Seconds between points (for count/rate)

    Returns:
        dict with submission status
    """
    auth = get_auth_instance()
    return _submit_metrics(metric_name, points, metric_type, tags, host, interval, auth=auth)


# ===== DASHBOARDS TOOLS =====


@mcp.tool()
def list_all_dashboards(filter_query: str | None = None, limit: int = 100) -> dict:
    """Browse all Datadog dashboards.

    Use this when: Want to see what dashboards exist or find specific dashboard.

    Args:
        filter_query: Search term to filter by name
        limit: Max dashboards to return (default: 100)

    Returns:
        dict with dashboard list including IDs, titles, URLs
    """
    auth = get_auth_instance()
    return _list_dashboards(filter_query, limit, auth=auth)


@mcp.tool()
def get_dashboard_details(dashboard_id: str) -> dict:
    """Get complete dashboard configuration and widgets.

    Use this when: Need to see what's in a dashboard or copy its configuration.

    Args:
        dashboard_id: Dashboard ID from list_all_dashboards

    Returns:
        dict with complete dashboard definition including all widgets
    """
    auth = get_auth_instance()
    return _get_dashboard(dashboard_id, auth=auth)


@mcp.tool()
def create_new_dashboard(
    title: str,
    layout_type: str,
    widgets: list[dict],
    description: str | None = None,
    template_variables: list[dict] | None = None,
    notify_list: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a new dashboard with custom widgets and layout.

    Use this when: User wants to visualize metrics, create monitoring view, or track KPIs.

    Layout types:
    - 'ordered': Timeline view (widgets stacked vertically)
    - 'free': Free-form placement (drag anywhere)

    Common widgets:
    - timeseries: Line/area charts
    - query_value: Single number
    - toplist: Top N values
    - heatmap: Intensity map

    Args:
        title: Dashboard name
        layout_type: 'ordered' or 'free'
        widgets: Widget definitions (see Datadog API docs)
        description: Optional description
        template_variables: Optional filters/variables
        notify_list: Optional notification handles
        tags: Optional tags

    Returns:
        dict with created dashboard ID and URL
    """
    auth = get_auth_instance()
    return _create_dashboard(
        title, layout_type, widgets, description, template_variables, notify_list, tags, auth=auth
    )


@mcp.tool()
def update_existing_dashboard(
    dashboard_id: str,
    title: str | None = None,
    widgets: list[dict] | None = None,
    description: str | None = None,
    template_variables: list[dict] | None = None,
    layout_type: str | None = None,
    notify_list: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Modify an existing dashboard.

    Use this when: Need to add widgets, change layout, or update dashboard config.

    Args:
        dashboard_id: Dashboard to update
        title: New title (optional)
        widgets: New widgets (optional, replaces all)
        description: New description (optional)
        template_variables: New variables (optional)
        layout_type: New layout (optional)
        notify_list: New notifications (optional)
        tags: New tags (optional)

    Returns:
        dict with update status
    """
    auth = get_auth_instance()
    return _update_dashboard(
        dashboard_id,
        title,
        widgets,
        description,
        template_variables,
        layout_type,
        notify_list,
        tags,
        auth=auth,
    )


@mcp.tool()
def delete_dashboard(dashboard_id: str) -> dict:
    """Permanently delete a dashboard.

    Use this when: Dashboard is no longer needed.

    Args:
        dashboard_id: Dashboard to delete

    Returns:
        dict with deletion status
    """
    auth = get_auth_instance()
    return _delete_dashboard(dashboard_id, auth=auth)


# ===== APM / TRACES TOOLS =====


@mcp.tool()
def search_apm_traces(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int = 25,
    cursor: str | None = None,
    sort: str = "timestamp",
) -> dict:
    """Search distributed traces and spans for performance analysis (paginated).

    Use this when: Debugging slow requests, finding errors in services, or analyzing latency.

    Common queries:
    - Find errors: "service:api @error.message:*"
    - Slow requests: "service:web @duration:>1000000000"  (nanoseconds)
    - By status: "service:checkout @http.status_code:500"
    - By operation: "operation_name:http.request"
    - Custom tags: "@airline_name:aeromexico @session_id:*"

    Args:
        query: Search query using Datadog APM syntax (examples above)
        from_time: Start time - ISO 8601, date math like "now-1h", or timestamp ms
        to_time: End time - ISO 8601, date math like "now", or timestamp ms
        page_size: Spans per page (default: 25, max: 50)
        cursor: Pagination cursor from previous response
        sort: 'timestamp' or '-timestamp'

    Returns:
        Paginated spans including service, duration, tags, trace_id, next_cursor
    """
    auth = get_auth_instance()
    return _search_spans(query, from_time, to_time, page_size, cursor, sort, auth=auth)


@mcp.tool()
def get_full_trace(trace_id: str) -> dict:
    """Get complete trace with all spans and timing information.

    Use this when: Need to see full request flow across services (after finding trace ID).

    Args:
        trace_id: Trace identifier from search results

    Returns:
        dict with all spans, duration, root span, and service flow
    """
    auth = get_auth_instance()
    return _get_trace(trace_id, auth=auth)


@mcp.tool()
def list_apm_services(env: str | None = None, limit: int = 100) -> dict:
    """List all services sending APM data.

    Use this when: Want to see what services are instrumented or find service names.

    Args:
        env: Filter by environment ('prod', 'staging', etc.)
        limit: Max services to return (default: 100)

    Returns:
        dict with service names and count
    """
    auth = get_auth_instance()
    return _list_services(env, limit, auth=auth)


# ===== MONITORS / ALERTS TOOLS =====


@mcp.tool()
def list_all_monitors(
    group_states: str | None = None,
    name: str | None = None,
    tags: str | None = None,
    monitor_tags: str | None = None,
    with_downtimes: bool = False,
    limit: int = 100,
) -> dict:
    """Browse all monitors and their current alert states.

    Use this when: Want to see what's being monitored or check alert status.

    Filter options:
    - group_states: 'alert,warn,no data' - only show alerting monitors
    - name: Search by monitor name
    - tags: Filter by resource tags
    - monitor_tags: Filter by monitor-specific tags

    Args:
        group_states: Filter by state (see above)
        name: Monitor name search term
        tags: Resource tags filter
        monitor_tags: Monitor tags filter
        with_downtimes: Include muted monitors info
        limit: Max monitors to return (default: 100)

    Returns:
        dict with monitors including state, name, query, tags
    """
    auth = get_auth_instance()
    return _list_monitors(group_states, name, tags, monitor_tags, with_downtimes, limit, auth=auth)


@mcp.tool()
def get_monitor_details(monitor_id: int) -> dict:
    """Get complete monitor configuration and current status.

    Use this when: Need to see monitor details, thresholds, or notification settings.

    Args:
        monitor_id: Monitor ID from list_all_monitors

    Returns:
        dict with complete monitor config including query, thresholds, message
    """
    auth = get_auth_instance()
    return _get_monitor(monitor_id, auth=auth)


@mcp.tool()
def create_alert_monitor(
    name: str,
    monitor_type: str,
    query: str,
    message: str,
    tags: list[str] | None = None,
    priority: int | None = None,
    options: dict | None = None,
) -> dict:
    """Create a new monitor to alert on metrics, logs, or APM data.

    Use this when: User wants to get notified about issues, set up alerting, or monitor SLAs.

    Monitor types:
    - 'metric alert': Alert on metric thresholds (CPU > 80%)
    - 'log alert': Alert on log patterns (error rate)
    - 'trace-analytics alert': Alert on APM metrics (latency)
    - 'composite': Combine multiple monitors

    Query examples:
    - Metric: "avg(last_5m):avg:system.cpu.user{*} > 80"
    - Log: 'logs("status:error").index("*").rollup("count").last("5m") > 100'
    - APM: "avg(last_10m):trace.web.request{service:api}.errors.rate > 5"

    Args:
        name: Monitor name (descriptive)
        monitor_type: Type from list above
        query: Alert query (examples above)
        message: Notification text with @mentions (e.g., "@slack-alerts CPU high!")
        tags: Optional tags (e.g., ['team:backend', 'severity:high'])
        priority: 1-5 (1=P1/highest, 5=P5/lowest)
        options: Advanced settings (thresholds, evaluation_delay, etc.)

    Returns:
        dict with created monitor ID and configuration
    """
    auth = get_auth_instance()
    return _create_monitor(name, monitor_type, query, message, tags, priority, options, auth=auth)


@mcp.tool()
def update_alert_monitor(
    monitor_id: int,
    name: str | None = None,
    query: str | None = None,
    message: str | None = None,
    tags: list[str] | None = None,
    priority: int | None = None,
    options: dict | None = None,
) -> dict:
    """Modify an existing monitor's configuration.

    Use this when: Need to adjust thresholds, change notifications, or update alert logic.

    Args:
        monitor_id: Monitor to update
        name: New name (optional)
        query: New query (optional)
        message: New message (optional)
        tags: New tags (optional)
        priority: New priority (optional)
        options: New options (optional)

    Returns:
        dict with update status
    """
    auth = get_auth_instance()
    return _update_monitor(monitor_id, name, query, message, tags, priority, options, auth=auth)


@mcp.tool()
def delete_alert_monitor(monitor_id: int) -> dict:
    """Permanently remove a monitor.

    Use this when: Monitor is no longer needed.

    Args:
        monitor_id: Monitor to delete

    Returns:
        dict with deletion status
    """
    auth = get_auth_instance()
    return _delete_monitor(monitor_id, auth=auth)


@mcp.tool()
def silence_monitor(
    monitor_id: int, scope: str | None = None, end_timestamp: int | None = None
) -> dict:
    """Temporarily mute/silence monitor notifications.

    Use this when: Performing maintenance, testing, or known issues don't need alerts.

    Args:
        monitor_id: Monitor to mute
        scope: Mute only specific scope (e.g., 'host:web-01' or 'env:staging')
        end_timestamp: When to unmute (Unix timestamp). If not set, mutes indefinitely.

    Returns:
        dict with mute status
    """
    auth = get_auth_instance()
    return _mute_monitor(monitor_id, scope, end_timestamp, auth=auth)


@mcp.tool()
def unsilence_monitor(monitor_id: int, scope: str | None = None) -> dict:
    """Resume notifications from a muted monitor.

    Use this when: Maintenance complete or ready to receive alerts again.

    Args:
        monitor_id: Monitor to unmute
        scope: Unmute specific scope (must match mute scope)

    Returns:
        dict with unmute status
    """
    auth = get_auth_instance()
    return _unmute_monitor(monitor_id, scope, auth=auth)


def main() -> None:
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
