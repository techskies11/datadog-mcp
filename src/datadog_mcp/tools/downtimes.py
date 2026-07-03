"""Downtime tools for scheduling and managing scoped monitor silencing.

Downtimes are Datadog's purpose-built mechanism for muting a scope of
monitors (or one specific monitor) over a time window, as opposed to
`silence_monitor` which mutes exactly one monitor via its `options.silenced`
field. See each tool's docstring for guidance on which to use when.

`cancel_downtime` is intentionally NOT implemented: it is an irreversible
HTTP DELETE with no undo path, and the plan this module implements requires
explicit team sign-off before adding any destructive operation. A downtime
can still be effectively ended early via `update_downtime` by setting its
`end` time to now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from datadog_api_client.v2.api.downtimes_api import DowntimesApi
from datadog_api_client.v2.model.downtime_create_request import DowntimeCreateRequest
from datadog_api_client.v2.model.downtime_create_request_attributes import (
    DowntimeCreateRequestAttributes,
)
from datadog_api_client.v2.model.downtime_create_request_data import DowntimeCreateRequestData
from datadog_api_client.v2.model.downtime_monitor_identifier_id import DowntimeMonitorIdentifierId
from datadog_api_client.v2.model.downtime_monitor_identifier_tags import (
    DowntimeMonitorIdentifierTags,
)
from datadog_api_client.v2.model.downtime_resource_type import DowntimeResourceType
from datadog_api_client.v2.model.downtime_schedule_one_time_create_update_request import (
    DowntimeScheduleOneTimeCreateUpdateRequest,
)
from datadog_api_client.v2.model.downtime_update_request import DowntimeUpdateRequest
from datadog_api_client.v2.model.downtime_update_request_attributes import (
    DowntimeUpdateRequestAttributes,
)
from datadog_api_client.v2.model.downtime_update_request_data import DowntimeUpdateRequestData
from fastmcp import FastMCP
from pydantic import Field, model_validator

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY, WRITE_ADDITIVE, WRITE_OVERWRITE
from ..utils.auth import get_api_instance
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    finalize_list_response,
    format_error_response,
)
from ..utils.time import parse_time_value


class DowntimeSummary(DatadogModel):
    """One downtime, flattened from Datadog's `{id, type, attributes}` envelope.

    `schedule` is kept as an open dict rather than fully typed: Datadog
    downtimes support two mutually-exclusive schedule shapes (one-time vs
    recurring), and this server's `schedule_downtime`/`update_downtime` only
    create the one-time variant - re-modeling the recurring variant here
    would add a typed field that no tool in this server ever produces.
    """

    id: str | None = None
    scope: str | None = None
    message: str | None = None
    status: str | None = None
    monitor_id: int | None = None
    monitor_tags: list[str] = Field(default_factory=list)
    schedule: dict[str, Any] = Field(default_factory=dict)
    display_timezone: str | None = None
    mute_first_recovery_notification: bool | None = None
    canceled: str | None = None
    created: str | None = None
    modified: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_datadog_envelope(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("attributes"), dict):
            return data

        attrs = data["attributes"]
        monitor_identifier = attrs.get("monitor_identifier") or {}

        return {
            "id": data.get("id"),
            "scope": attrs.get("scope"),
            "message": attrs.get("message"),
            "status": attrs.get("status"),
            "monitor_id": monitor_identifier.get("monitor_id"),
            "monitor_tags": monitor_identifier.get("monitor_tags") or [],
            "schedule": attrs.get("schedule") or {},
            "display_timezone": attrs.get("display_timezone"),
            "mute_first_recovery_notification": attrs.get("mute_first_recovery_notification"),
            "canceled": attrs.get("canceled"),
            "created": attrs.get("created"),
            "modified": attrs.get("modified"),
        }


class ListDowntimesResponse(PaginatedListResponse):
    """Response for `list_downtimes`."""

    downtimes: list[DowntimeSummary] = Field(default_factory=list)


class GetDowntimeResponse(ToolResponse):
    """Response for `get_downtime`."""

    downtime: DowntimeSummary | None = None


class ScheduleDowntimeResponse(ToolResponse):
    """Response for `schedule_downtime`."""

    downtime: DowntimeSummary | None = None


class UpdateDowntimeResponse(ToolResponse):
    """Response for `update_downtime`."""

    downtime: DowntimeSummary | None = None


def _to_datetime(value: int | str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(parse_time_value(value), tz=timezone.utc)


def _existing_schedule_datetime(existing_schedule: dict[str, Any], key: str) -> datetime | None:
    """Read `start`/`end` back out of a schedule dict serialized via `.to_dict()`.

    `.to_dict()` renders `datetime` fields as ISO strings; when only one of
    `start`/`end` is being changed, the other needs to be resent as a real
    `datetime` (not the raw string) to satisfy the update request's typing.
    """
    raw = existing_schedule.get(key)
    if raw is None or isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def _build_monitor_identifier(
    monitor_id: int | None, monitor_tags: list[str] | None
) -> DowntimeMonitorIdentifierId | DowntimeMonitorIdentifierTags | None:
    if monitor_id is not None:
        return DowntimeMonitorIdentifierId(monitor_id=monitor_id)
    if monitor_tags:
        return DowntimeMonitorIdentifierTags(monitor_tags=monitor_tags)
    return None


def _list_downtimes(current_only: bool, limit: int, auth: DatadogAuth) -> ListDowntimesResponse:
    api_instance = get_api_instance(DowntimesApi, auth)

    try:
        response = api_instance.list_downtimes(current_only=current_only)
        downtimes = [
            DowntimeSummary.model_validate(d.to_dict()) for d in (response.data or [])[:limit]
        ]

        result = ListDowntimesResponse(downtimes=downtimes)
        return finalize_list_response(result, "downtimes")

    except Exception as e:  # noqa: BLE001
        return format_error_response(
            ListDowntimesResponse, e, required_scope="monitors_downtime_write"
        )


def _get_downtime(downtime_id: str, auth: DatadogAuth) -> GetDowntimeResponse:
    api_instance = get_api_instance(DowntimesApi, auth)

    try:
        response = api_instance.get_downtime(downtime_id)
        downtime = (
            DowntimeSummary.model_validate(response.data.to_dict()) if response.data else None
        )
        return GetDowntimeResponse(downtime=downtime)

    except Exception as e:  # noqa: BLE001
        return format_error_response(
            GetDowntimeResponse, e, required_scope="monitors_downtime_write"
        )


def _schedule_downtime(
    scope: str,
    message: str,
    monitor_id: int | None,
    monitor_tags: list[str] | None,
    start: int | str,
    end: int | str | None,
    display_timezone: str | None,
    mute_first_recovery_notification: bool,
    auth: DatadogAuth,
) -> ScheduleDowntimeResponse:
    api_instance = get_api_instance(DowntimesApi, auth)

    try:
        attrs_kwargs: dict[str, Any] = {
            "scope": scope,
            "message": message,
            "schedule": DowntimeScheduleOneTimeCreateUpdateRequest(
                start=_to_datetime(start), end=_to_datetime(end)
            ),
            "mute_first_recovery_notification": mute_first_recovery_notification,
        }
        monitor_identifier = _build_monitor_identifier(monitor_id, monitor_tags)
        if monitor_identifier is not None:
            attrs_kwargs["monitor_identifier"] = monitor_identifier
        if display_timezone:
            attrs_kwargs["display_timezone"] = display_timezone

        body = DowntimeCreateRequest(
            data=DowntimeCreateRequestData(
                type=DowntimeResourceType.DOWNTIME,
                attributes=DowntimeCreateRequestAttributes(**attrs_kwargs),
            )
        )
        response = api_instance.create_downtime(body=body)
        downtime = (
            DowntimeSummary.model_validate(response.data.to_dict()) if response.data else None
        )
        return ScheduleDowntimeResponse(downtime=downtime)

    except Exception as e:  # noqa: BLE001
        return format_error_response(
            ScheduleDowntimeResponse, e, required_scope="monitors_downtime_write"
        )


def _update_downtime(
    downtime_id: str,
    scope: str | None,
    message: str | None,
    monitor_id: int | None,
    monitor_tags: list[str] | None,
    start: int | str | None,
    end: int | str | None,
    auth: DatadogAuth,
) -> UpdateDowntimeResponse:
    api_instance = get_api_instance(DowntimesApi, auth)

    try:
        existing = api_instance.get_downtime(downtime_id)
        existing_attrs = existing.data.attributes if existing.data else None

        attrs_kwargs: dict[str, Any] = {}
        if scope is not None:
            attrs_kwargs["scope"] = scope
        if message is not None:
            attrs_kwargs["message"] = message

        monitor_identifier = _build_monitor_identifier(monitor_id, monitor_tags)
        if monitor_identifier is not None:
            attrs_kwargs["monitor_identifier"] = monitor_identifier

        if start is not None or end is not None:
            existing_schedule = existing_attrs.schedule.to_dict() if existing_attrs else {}
            attrs_kwargs["schedule"] = DowntimeScheduleOneTimeCreateUpdateRequest(
                start=_to_datetime(start)
                or _existing_schedule_datetime(existing_schedule, "start"),
                end=_to_datetime(end) or _existing_schedule_datetime(existing_schedule, "end"),
            )

        body = DowntimeUpdateRequest(
            data=DowntimeUpdateRequestData(
                id=downtime_id,
                type=DowntimeResourceType.DOWNTIME,
                attributes=DowntimeUpdateRequestAttributes(**attrs_kwargs),
            )
        )
        response = api_instance.update_downtime(downtime_id, body=body)
        downtime = (
            DowntimeSummary.model_validate(response.data.to_dict()) if response.data else None
        )
        return UpdateDowntimeResponse(downtime=downtime)

    except Exception as e:  # noqa: BLE001
        return format_error_response(
            UpdateDowntimeResponse, e, required_scope="monitors_downtime_write"
        )


def register_downtime_tools(mcp: FastMCP) -> None:
    """Register downtime list/get/schedule/update tools on `mcp`.

    `cancel_downtime` is intentionally not registered - see this module's
    docstring.
    """

    @mcp.tool(annotations=READ_ONLY)
    def list_downtimes(current_only: bool = True, limit: int = 100) -> ListDowntimesResponse:
        """Browse scheduled/active downtimes (scoped monitor mutes).

        Use this when: want to see what's currently muted org-wide, or audit
        upcoming maintenance windows.

        Args:
            current_only: If True (default), only include active/upcoming downtimes;
                if False, also include past/expired ones
            limit: Max downtimes to return (default: 100)
        """
        return _list_downtimes(current_only, limit, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def get_downtime(downtime_id: str) -> GetDowntimeResponse:
        """Get complete details of a specific downtime.

        Use this when: need to see a downtime's exact scope, schedule, or status.

        Args:
            downtime_id: Downtime ID from list_downtimes
        """
        return _get_downtime(downtime_id, get_auth_instance())

    @mcp.tool(annotations=WRITE_ADDITIVE)
    def schedule_downtime(
        scope: str,
        message: str,
        monitor_id: int | None = None,
        monitor_tags: list[str] | None = None,
        start: int | str = "now",
        end: int | str | None = None,
        display_timezone: str | None = None,
        mute_first_recovery_notification: bool = False,
    ) -> ScheduleDowntimeResponse:
        """Schedule a downtime to mute a scope of monitors (or one monitor) over a time window.

        Use this when: silencing many monitors at once by scope/tag (e.g. "mute all
        alerts for env:staging this weekend"), or muting on a schedule with a known
        end time. For muting exactly one already-known monitor with no scheduling
        needs, silence_monitor is simpler. At most one of monitor_id/monitor_tags
        should be set; if neither is set, the downtime applies to all monitors
        matching scope.

        Examples:
            schedule_downtime("env:staging", "Weekend maintenance", start="now", end="now+2d")
            schedule_downtime("*", "Planned outage", monitor_id=12345, end="now+1h")

        Args:
            scope: Scope to mute, as a tag query (e.g. "env:staging", "team:backend",
                or "*" for everything matching monitor_id/monitor_tags)
            message: Reason for the downtime (shown in notifications)
            monitor_id: Optional single monitor ID to restrict this downtime to
            monitor_tags: Optional monitor tags to restrict this downtime to
                (mutually exclusive with monitor_id)
            start: ISO 8601, relative date math (e.g. "now", "now+1h"), or a Unix
                timestamp (default: "now")
            end: Same accepted formats as start; omit for an open-ended downtime
                that must be ended later via update_downtime
            display_timezone: IANA timezone for displaying the schedule (e.g. "America/New_York")
            mute_first_recovery_notification: If True, suppress the first recovery
                notification after the downtime ends (default: False)
        """
        return _schedule_downtime(
            scope,
            message,
            monitor_id,
            monitor_tags,
            start,
            end,
            display_timezone,
            mute_first_recovery_notification,
            get_auth_instance(),
        )

    @mcp.tool(annotations=WRITE_OVERWRITE)
    def update_downtime(
        downtime_id: str,
        scope: str | None = None,
        message: str | None = None,
        monitor_id: int | None = None,
        monitor_tags: list[str] | None = None,
        start: int | str | None = None,
        end: int | str | None = None,
    ) -> UpdateDowntimeResponse:
        """Modify an existing downtime's scope, schedule, or message.

        Use this when: need to extend/shorten a downtime's window, change its
        scope, or end it early (set end to "now"). There is no undo tool -
        the previous downtime configuration is not recoverable once overwritten.

        Args:
            downtime_id: Downtime to update
            scope: New scope (optional)
            message: New message (optional)
            monitor_id: New single-monitor restriction (optional)
            monitor_tags: New monitor-tags restriction (optional)
            start: New start time - ISO 8601, relative date math (e.g. "now-1h",
                "now+2d"), or a Unix timestamp (optional)
            end: New end time - same accepted formats as start (optional; set to
                "now" to end the downtime immediately)
        """
        return _update_downtime(
            downtime_id, scope, message, monitor_id, monitor_tags, start, end, get_auth_instance()
        )
