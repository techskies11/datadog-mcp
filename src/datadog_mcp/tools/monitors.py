"""Monitors tools for creating, managing, searching, and validating Datadog monitors."""

from __future__ import annotations

from typing import Any, Literal

from datadog_api_client.exceptions import ApiException
from datadog_api_client.v1.api.monitors_api import MonitorsApi
from datadog_api_client.v1.model.monitor import Monitor
from datadog_api_client.v1.model.monitor_options import MonitorOptions
from datadog_api_client.v1.model.monitor_type import MonitorType
from datadog_api_client.v1.model.monitor_update_request import MonitorUpdateRequest
from fastmcp import FastMCP
from pydantic import Field

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY, STATE_TOGGLE, WRITE_ADDITIVE, WRITE_OVERWRITE
from ..utils.auth import get_api_instance
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    finalize_list_response,
    format_error_response,
)

MonitorTypeName = Literal[
    "metric alert",
    "service check",
    "event alert",
    "query alert",
    "composite",
    "log alert",
    "rum alert",
    "trace-analytics alert",
]

_MONITOR_TYPE_MAP: dict[MonitorTypeName, MonitorType] = {
    "metric alert": MonitorType.METRIC_ALERT,
    "service check": MonitorType.SERVICE_CHECK,
    "event alert": MonitorType.EVENT_ALERT,
    "query alert": MonitorType.QUERY_ALERT,
    "composite": MonitorType.COMPOSITE,
    "log alert": MonitorType.LOG_ALERT,
    "rum alert": MonitorType.RUM_ALERT,
    "trace-analytics alert": MonitorType.TRACE_ANALYTICS_ALERT,
}


class MonitorSummary(DatadogModel):
    """One monitor's basic info, as returned by `list_all_monitors`."""

    id: int | None = None
    name: str | None = None
    type: str | None = None
    query: str | None = None
    message: str | None = None
    tags: list[str] = Field(default_factory=list)
    overall_state: str | None = None
    created: str | None = None
    modified: str | None = None
    priority: int | None = None


class ListAllMonitorsResponse(PaginatedListResponse):
    """Response for `list_all_monitors`."""

    monitors: list[MonitorSummary] = Field(default_factory=list)


class GetMonitorDetailsResponse(ToolResponse):
    """Response for `get_monitor_details`.

    `monitor` is kept as an open dict rather than a fully typed model: a
    monitor's `options` shape (thresholds, notification behavior, scheduling)
    varies significantly by monitor type, and re-modeling all of Datadog's
    monitor option schemas is out of scope for this server.
    """

    monitor: dict[str, Any] | None = None


class CreateMonitorResponse(ToolResponse):
    """Response for `create_alert_monitor`."""

    monitor_id: int | None = None
    name: str | None = None
    type: str | None = None


class UpdateMonitorResponse(ToolResponse):
    """Response for `update_alert_monitor`."""

    monitor_id: int | None = None
    name: str | None = None


class MuteMonitorResponse(ToolResponse):
    """Response for `silence_monitor`."""

    monitor_id: int | None = None
    message: str | None = None
    scope: str | None = None
    end_timestamp: int | None = None


class UnmuteMonitorResponse(ToolResponse):
    """Response for `unsilence_monitor`."""

    monitor_id: int | None = None
    message: str | None = None
    scope: str | None = None


class SearchMonitorsResult(DatadogModel):
    """One monitor from `search_monitors`."""

    id: int | None = None
    name: str | None = None
    type: str | None = None
    query: str | None = None
    status: str | None = None
    tags: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)


class SearchMonitorsResponse(PaginatedListResponse):
    """Response for `search_monitors`."""

    monitors: list[SearchMonitorsResult] = Field(default_factory=list)
    total_count: int | None = None


class ValidateMonitorResponse(ToolResponse):
    """Response for `validate_monitor`.

    `success=False`/`error` are reserved for the *tool* failing (network,
    permissions); an invalid monitor definition is a normal, expected
    outcome of validation and is reported via `valid`/`validation_error`
    instead, so an agent can tell "the check didn't run" apart from
    "the check ran and found a problem".
    """

    valid: bool = False
    validation_error: str | None = None


def list_monitors_summary(
    group_states: str | None,
    name: str | None,
    tags: str | None,
    monitor_tags: str | None,
    with_downtimes: bool,
    limit: int,
    auth: DatadogAuth,
) -> ListAllMonitorsResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        kwargs: dict[str, str | bool] = {}
        if group_states:
            kwargs["group_states"] = group_states
        if name:
            kwargs["name"] = name
        if tags:
            kwargs["tags"] = tags
        if monitor_tags:
            kwargs["monitor_tags"] = monitor_tags
        if with_downtimes:
            kwargs["with_downtimes"] = with_downtimes

        response = api_instance.list_monitors(**kwargs)  # type: ignore[arg-type]
        monitors = [
            MonitorSummary.model_validate(m.to_dict())  # type: ignore[no-untyped-call]
            for m in (response or [])[:limit]
        ]

        result = ListAllMonitorsResponse(monitors=monitors)
        return finalize_list_response(result, "monitors")

    except Exception as e:  # noqa: BLE001
        return format_error_response(ListAllMonitorsResponse, e, required_scope="monitors_read")


def _get_monitor(monitor_id: int, auth: DatadogAuth) -> GetMonitorDetailsResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        response = api_instance.get_monitor(monitor_id)
        return GetMonitorDetailsResponse(monitor=response.to_dict())  # type: ignore[no-untyped-call]

    except Exception as e:  # noqa: BLE001
        return format_error_response(GetMonitorDetailsResponse, e, required_scope="monitors_read")


def _create_monitor(
    name: str,
    monitor_type: MonitorTypeName,
    query: str,
    message: str,
    tags: list[str] | None,
    priority: int | None,
    options: dict[str, Any] | None,
    auth: DatadogAuth,
) -> CreateMonitorResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        monitor_data: dict[str, Any] = {
            "name": name,
            "type": _MONITOR_TYPE_MAP[monitor_type],
            "query": query,
            "message": message,
        }
        if tags:
            monitor_data["tags"] = tags
        if priority:
            monitor_data["priority"] = priority
        if options:
            monitor_data["options"] = MonitorOptions(**options)

        response = api_instance.create_monitor(body=Monitor(**monitor_data))

        return CreateMonitorResponse(
            monitor_id=response.id,
            name=response.name or name,
            type=str(response.type or monitor_type),
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(CreateMonitorResponse, e, required_scope="monitors_write")


def _update_monitor(
    monitor_id: int,
    name: str | None,
    query: str | None,
    message: str | None,
    tags: list[str] | None,
    priority: int | None,
    options: dict[str, Any] | None,
    auth: DatadogAuth,
) -> UpdateMonitorResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        existing = api_instance.get_monitor(monitor_id)

        monitor_data: dict[str, Any] = {
            "name": name or existing.name,
            "type": existing.type,
            "query": query or existing.query,
            "message": message or existing.message,
        }
        if tags is not None:
            monitor_data["tags"] = tags
        elif existing.tags:
            monitor_data["tags"] = existing.tags

        if priority is not None:
            monitor_data["priority"] = priority
        elif existing.priority:
            monitor_data["priority"] = existing.priority

        if options is not None:
            monitor_data["options"] = MonitorOptions(**options)
        elif existing.options:
            monitor_data["options"] = existing.options

        response = api_instance.update_monitor(
            monitor_id, body=MonitorUpdateRequest(**monitor_data)
        )

        return UpdateMonitorResponse(
            monitor_id=response.id or monitor_id, name=response.name or name
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(UpdateMonitorResponse, e, required_scope="monitors_write")


def _mute_monitor(
    monitor_id: int, scope: str | None, end_timestamp: int | None, auth: DatadogAuth
) -> MuteMonitorResponse:
    # datadog-api-client 2.57 dropped the dedicated mute_monitor/unmute_monitor
    # endpoints; Datadog's current mechanism is the (still-supported)
    # options.silenced map on the monitor itself, applied via update_monitor.
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        existing = api_instance.get_monitor(monitor_id)
        options = existing.options.to_dict() if existing.options else {}
        silenced: dict[str, int | None] = dict(options.get("silenced") or {})
        silenced[scope or "*"] = end_timestamp
        options["silenced"] = silenced

        api_instance.update_monitor(
            monitor_id,
            body=MonitorUpdateRequest(
                name=existing.name,
                type=existing.type,
                query=existing.query,
                message=existing.message,
                options=MonitorOptions(**options),
            ),
        )

        return MuteMonitorResponse(
            monitor_id=monitor_id,
            message="Monitor muted successfully",
            scope=scope,
            end_timestamp=end_timestamp,
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(MuteMonitorResponse, e, required_scope="monitors_write")


def _unmute_monitor(monitor_id: int, scope: str | None, auth: DatadogAuth) -> UnmuteMonitorResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        existing = api_instance.get_monitor(monitor_id)
        options = existing.options.to_dict() if existing.options else {}
        silenced: dict[str, int | None] = dict(options.get("silenced") or {})
        silenced.pop(scope or "*", None)
        options["silenced"] = silenced

        api_instance.update_monitor(
            monitor_id,
            body=MonitorUpdateRequest(
                name=existing.name,
                type=existing.type,
                query=existing.query,
                message=existing.message,
                options=MonitorOptions(**options),
            ),
        )

        return UnmuteMonitorResponse(
            monitor_id=monitor_id, message="Monitor unmuted successfully", scope=scope
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(UnmuteMonitorResponse, e, required_scope="monitors_write")


def _search_monitors(query: str, per_page: int, auth: DatadogAuth) -> SearchMonitorsResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        response = api_instance.search_monitors(query=query, per_page=per_page)

        monitors = [
            SearchMonitorsResult.model_validate(m.to_dict()) for m in (response.monitors or [])
        ]
        total_count = response.counts.total_count if response.counts else None

        result = SearchMonitorsResponse(monitors=monitors, total_count=total_count)
        return finalize_list_response(result, "monitors")

    except Exception as e:  # noqa: BLE001
        return format_error_response(SearchMonitorsResponse, e, required_scope="monitors_read")


def _validate_monitor(
    monitor_type: MonitorTypeName, query: str, message: str | None, auth: DatadogAuth
) -> ValidateMonitorResponse:
    api_instance = get_api_instance(MonitorsApi, auth)

    try:
        api_instance.validate_monitor(
            body=Monitor(
                name="validation-only (never created)",
                type=_MONITOR_TYPE_MAP[monitor_type],
                query=query,
                message=message or "validation only",
            )
        )
        return ValidateMonitorResponse(valid=True)

    except ApiException as e:
        if e.status == 400:
            return ValidateMonitorResponse(valid=False, validation_error=str(e))
        return format_error_response(ValidateMonitorResponse, e, required_scope="monitors_write")
    except Exception as e:  # noqa: BLE001
        return format_error_response(ValidateMonitorResponse, e, required_scope="monitors_write")


def register_monitor_tools(mcp: FastMCP) -> None:
    """Register monitor CRUD, mute/unmute, search, and validation tools on `mcp`."""

    @mcp.tool(annotations=READ_ONLY)
    def list_all_monitors(
        group_states: str | None = None,
        name: str | None = None,
        tags: str | None = None,
        monitor_tags: str | None = None,
        with_downtimes: bool = False,
        limit: int = 100,
    ) -> ListAllMonitorsResponse:
        """Browse all monitors and their current alert states.

        Use this when: want to see what's being monitored or check alert status.
        For a faceted/full-text search instead of exact filters, use search_monitors.

        Args:
            group_states: Filter by state, e.g. "alert,warn,no data" - only show alerting monitors
            name: Monitor name search term
            tags: Resource tags filter (e.g. "env:prod,service:api")
            monitor_tags: Monitor-specific tags filter
            with_downtimes: Include muted-monitor info
            limit: Max monitors to return (default: 100)
        """
        return list_monitors_summary(
            group_states, name, tags, monitor_tags, with_downtimes, limit, get_auth_instance()
        )

    @mcp.tool(annotations=READ_ONLY)
    def get_monitor_details(monitor_id: int) -> GetMonitorDetailsResponse:
        """Get complete monitor configuration and current status.

        Use this when: need to see monitor details, thresholds, or notification settings.

        Args:
            monitor_id: Monitor ID from list_all_monitors or search_monitors
        """
        return _get_monitor(monitor_id, get_auth_instance())

    @mcp.tool(annotations=WRITE_ADDITIVE)
    def create_alert_monitor(
        name: str,
        monitor_type: MonitorTypeName,
        query: str,
        message: str,
        tags: list[str] | None = None,
        priority: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> CreateMonitorResponse:
        """Create a new monitor to alert on metrics, logs, or APM data.

        Use this when: user wants to get notified about issues, set up alerting, or monitor SLAs.
        Consider validate_monitor first to check the query syntax before creating.

        Query examples:
        - Metric: "avg(last_5m):avg:system.cpu.user{*} > 80"
        - Log: 'logs("status:error").index("*").rollup("count").last("5m") > 100'
        - APM: "avg(last_10m):trace.web.request{service:api}.errors.rate > 5"

        Args:
            name: Monitor name (descriptive)
            monitor_type: One of "metric alert", "service check", "event alert", "query alert",
                "composite", "log alert", "rum alert", "trace-analytics alert"
            query: Alert query (examples above)
            message: Notification text with @mentions (e.g. "@slack-alerts CPU high!")
            tags: Optional tags (e.g. ["team:backend", "severity:high"])
            priority: 1-5 (1=P1/highest, 5=P5/lowest)
            options: Advanced settings (thresholds, evaluation_delay, notify_no_data, etc.)
        """
        return _create_monitor(
            name, monitor_type, query, message, tags, priority, options, get_auth_instance()
        )

    @mcp.tool(annotations=WRITE_OVERWRITE)
    def update_alert_monitor(
        monitor_id: int,
        name: str | None = None,
        query: str | None = None,
        message: str | None = None,
        tags: list[str] | None = None,
        priority: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> UpdateMonitorResponse:
        """Modify an existing monitor's configuration. Overwrites given fields; rest is unchanged.

        Use this when: need to adjust thresholds, change notifications, or update alert logic.
        There is no undo tool - the previous configuration is not recoverable once overwritten.

        Args:
            monitor_id: Monitor to update
            name: New name (optional)
            query: New query (optional)
            message: New message (optional)
            tags: New tags (optional)
            priority: New priority (optional)
            options: New options (optional)
        """
        return _update_monitor(
            monitor_id, name, query, message, tags, priority, options, get_auth_instance()
        )

    @mcp.tool(annotations=STATE_TOGGLE)
    def silence_monitor(
        monitor_id: int, scope: str | None = None, end_timestamp: int | None = None
    ) -> MuteMonitorResponse:
        """Temporarily mute/silence monitor notifications.

        Use this when: performing maintenance, testing, or a known issue doesn't need alerts
        right now, for a single monitor. For muting many monitors on a schedule by scope
        (e.g. "all monitors in this env, this weekend"), use schedule_downtime instead -
        it is Datadog's purpose-built tool for scheduled, scoped silencing.

        Args:
            monitor_id: Monitor to mute
            scope: Mute only a specific scope (e.g. "host:web-01" or "env:staging")
            end_timestamp: Unix timestamp to auto-unmute at; mutes indefinitely if omitted
        """
        return _mute_monitor(monitor_id, scope, end_timestamp, get_auth_instance())

    @mcp.tool(annotations=STATE_TOGGLE)
    def unsilence_monitor(monitor_id: int, scope: str | None = None) -> UnmuteMonitorResponse:
        """Resume notifications from a muted monitor.

        Use this when: maintenance is complete or ready to receive alerts again.

        Args:
            monitor_id: Monitor to unmute
            scope: Unmute a specific scope (must match the mute scope)
        """
        return _unmute_monitor(monitor_id, scope, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def search_monitors(query: str = "*", per_page: int = 30) -> SearchMonitorsResponse:
        """Full-text/faceted search across monitors (e.g. by tag, status, or text in the query/name).

        Use this when: list_all_monitors's exact-match filters aren't enough - e.g.
        searching monitor names/queries by substring across facets at once.

        Examples:
            search_monitors("status:alert")
            search_monitors("tag:env:prod service:checkout")

        Args:
            query: Search syntax combining facets like status, tag, type, and free text
                (default: "*", i.e. all monitors)
            per_page: Results per page (default: 30)
        """
        return _search_monitors(query, per_page, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def validate_monitor(
        monitor_type: MonitorTypeName, query: str, message: str | None = None
    ) -> ValidateMonitorResponse:
        """Validate a monitor query's syntax without creating anything.

        Use this when: want to check a monitor definition is well-formed before calling
        create_alert_monitor, especially for hand-built queries. This never creates,
        modifies, or persists a monitor - it is a pure syntax/semantics check.

        Note: validating a "log alert" monitor may additionally require the app key to
        have log data read access without further scoping; if that's missing you will
        see a permission error here specifically for log-type queries even though other
        monitor types validate fine.

        Args:
            monitor_type: Same values as create_alert_monitor's monitor_type
            query: The monitor query to validate
            message: Optional notification message (only affects validation of @-mentions)
        """
        return _validate_monitor(monitor_type, query, message, get_auth_instance())
