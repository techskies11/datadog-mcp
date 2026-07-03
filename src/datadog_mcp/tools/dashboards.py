"""Dashboard tools for creating and managing Datadog dashboards."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, cast
from urllib.parse import quote

from datadog_api_client.v1.api.dashboards_api import DashboardsApi
from datadog_api_client.v1.model.dashboard import Dashboard
from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

VALID_LAYOUT_TYPES = ("ordered", "free")


class _WidgetRequestSpec(BaseModel):
    """Minimal shared shape of a widget `requests[]` entry: always needs a query."""

    model_config = ConfigDict(extra="allow")

    q: str


class TimeseriesWidgetDefinition(BaseModel):
    """Required shape of a `timeseries` widget's `definition`, for pre-flight validation.

    `extra="allow"` because Datadog's real schema has many more optional
    fields (`yaxis`, `markers`, `events`, ...) that this server does not
    need to police - only the fields that most commonly cause a rejected
    dashboard create/update are validated here.
    """

    model_config = ConfigDict(extra="allow")

    type: Literal["timeseries"]
    requests: list[_WidgetRequestSpec] = Field(min_length=1)
    title: str | None = None


class QueryValueWidgetDefinition(BaseModel):
    """Required shape of a `query_value` widget's `definition`."""

    model_config = ConfigDict(extra="allow")

    type: Literal["query_value"]
    requests: list[_WidgetRequestSpec] = Field(min_length=1)
    title: str | None = None


class ToplistWidgetDefinition(BaseModel):
    """Required shape of a `toplist` widget's `definition`."""

    model_config = ConfigDict(extra="allow")

    type: Literal["toplist"]
    requests: list[_WidgetRequestSpec] = Field(min_length=1)
    title: str | None = None


_KNOWN_WIDGET_DEFINITIONS: dict[str, type[BaseModel]] = {
    "timeseries": TimeseriesWidgetDefinition,
    "query_value": QueryValueWidgetDefinition,
    "toplist": ToplistWidgetDefinition,
}


def _validate_known_widgets(widgets: list[dict[str, Any]]) -> str | None:
    """Pre-flight validation for the widget types this server models explicitly.

    Widgets are still passed straight through to Datadog for any type not in
    `_KNOWN_WIDGET_DEFINITIONS` (Datadog has dozens of widget types; modeling
    all of them here would be a large, low-value maintenance burden) - this
    only catches the most common mistakes (missing `requests`, wrong `type`)
    for the 3 widget types explicitly listed in `datadog://widget-templates`
    before spending an API call finding out.

    Returns an error message for the first invalid widget found, or `None`
    if every recognized widget passed validation.
    """
    for index, widget in enumerate(widgets):
        definition = widget.get("definition") if isinstance(widget, dict) else None
        widget_type = definition.get("type") if isinstance(definition, dict) else None
        if not isinstance(widget_type, str):
            continue
        model_cls = _KNOWN_WIDGET_DEFINITIONS.get(widget_type)
        if model_cls is None:
            continue
        try:
            model_cls.model_validate(definition)
        except ValidationError as e:
            return f"Widget #{index} (type={widget_type!r}) failed validation: {e}"
    return None


def _dashboard_request_headers(api_client: Any) -> dict[str, str]:
    """Headers for a dashboard GET, matching the official client (auth + defaults)."""
    defaults = cast(Mapping[Any, Any], api_client.default_headers)
    headers: dict[str, str] = {str(k): str(v) for k, v in defaults.items()}
    for auth_conf in api_client.configuration.auth_settings().values():
        if auth_conf.get("in") == "header" and auth_conf.get("value") is not None:
            headers[str(auth_conf["key"])] = str(auth_conf["value"])
    headers.setdefault("Accept", "application/json")
    return headers


def _get_dashboard_json_dict(api_instance: DashboardsApi, dashboard_id: str) -> dict[str, Any]:
    """GET /api/v1/dashboard/{id} and return decoded JSON without OpenAPI model trees.

    ``DashboardsApi.get_dashboard`` + ``to_dict()`` can raise ``IndexError`` (``list index
    out of range``) from ``ModelComposed.get_oneof_instance`` when Datadog returns widget
    shapes the installed ``datadog-api-client`` does not map onto composed oneOf schemas
    (common with newer dashboard features). Raw JSON avoids that path entirely.
    """
    client = api_instance.api_client
    safe_id = quote(dashboard_id, safe="")
    url = f"{client.configuration.host}/api/v1/dashboard/{safe_id}"
    raw = client.rest_client.request(
        "GET",
        url,
        query_params=[],
        headers=_dashboard_request_headers(client),
        post_params=[],
        body=None,
        preload_content=True,
        request_timeout=client.configuration.request_timeout,
    )
    decoded: object = json.loads(raw.data.decode("utf-8"))
    if not isinstance(decoded, dict):
        msg = "Datadog dashboard API returned non-object JSON"
        raise TypeError(msg)
    return cast(dict[str, Any], decoded)


class DashboardSummary(DatadogModel):
    """One dashboard's basic info, as returned by `list_all_dashboards`."""

    id: str | None = None
    title: str | None = None
    description: str | None = None
    author_handle: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    url: str | None = None
    is_read_only: bool = False
    layout_type: str | None = None


class ListAllDashboardsResponse(PaginatedListResponse):
    """Response for `list_all_dashboards`."""

    dashboards: list[DashboardSummary] = Field(default_factory=list)


class DashboardWidgetSummary(DatadogModel):
    """One widget's definition within a dashboard."""

    definition_type: str | None = None
    title: str | None = None
    definition: dict[str, Any] = Field(default_factory=dict)


class GetDashboardDetailsResponse(PaginatedListResponse):
    """Response for `get_dashboard_details`.

    Inherits the truncation machinery from `PaginatedListResponse`: if a
    dashboard has enough widgets to exceed the response size budget, the
    `widgets` list itself is truncated (with `truncated`/`warning`/
    `total_available` set) rather than returning an unbounded multi-hundred-KB
    payload, which is what the pre-Pydantic implementation did.
    """

    dashboard_id: str | None = None
    title: str | None = None
    description: str | None = None
    layout_type: str | None = None
    url: str | None = None
    widgets: list[DashboardWidgetSummary] = Field(default_factory=list)
    template_variables: list[dict[str, Any]] = Field(default_factory=list)
    notify_list: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CreateDashboardResponse(ToolResponse):
    """Response for `create_new_dashboard`."""

    dashboard_id: str | None = None
    url: str | None = None
    title: str | None = None


class UpdateDashboardResponse(ToolResponse):
    """Response for `update_existing_dashboard`."""

    dashboard_id: str | None = None
    url: str | None = None
    title: str | None = None


def _list_dashboards(
    filter_query: str | None, limit: int, auth: DatadogAuth
) -> ListAllDashboardsResponse:
    api_instance = get_api_instance(DashboardsApi, auth)

    try:
        response = api_instance.list_dashboards()

        dashboards: list[DashboardSummary] = []
        for dashboard in response.dashboards or []:
            summary = DashboardSummary.model_validate(dashboard.to_dict())
            if filter_query and filter_query.lower() not in (summary.title or "").lower():
                continue
            dashboards.append(summary)
            if len(dashboards) >= limit:
                break

        result = ListAllDashboardsResponse(dashboards=dashboards)
        return finalize_list_response(result, "dashboards")

    except Exception as e:  # noqa: BLE001
        return format_error_response(ListAllDashboardsResponse, e, required_scope="dashboards_read")


def _get_dashboard(dashboard_id: str, auth: DatadogAuth) -> GetDashboardDetailsResponse:
    api_instance = get_api_instance(DashboardsApi, auth)

    try:
        raw = _get_dashboard_json_dict(api_instance, dashboard_id)

        widgets = [
            DashboardWidgetSummary(
                definition_type=(w.get("definition") or {}).get("type"),
                title=(w.get("definition") or {}).get("title"),
                definition=w.get("definition") or {},
            )
            for w in raw.get("widgets", [])
        ]

        result = GetDashboardDetailsResponse(
            dashboard_id=dashboard_id,
            title=raw.get("title"),
            description=raw.get("description"),
            layout_type=raw.get("layout_type"),
            url=raw.get("url"),
            widgets=widgets,
            template_variables=raw.get("template_variables") or [],
            notify_list=raw.get("notify_list") or [],
            tags=raw.get("tags") or [],
        )
        return finalize_list_response(result, "widgets")

    except Exception as e:  # noqa: BLE001
        return format_error_response(
            GetDashboardDetailsResponse, e, required_scope="dashboards_read"
        )


def _create_dashboard(
    title: str,
    layout_type: str,
    widgets: list[dict[str, Any]],
    description: str | None,
    template_variables: list[dict[str, Any]] | None,
    notify_list: list[str] | None,
    tags: list[str] | None,
    auth: DatadogAuth,
) -> CreateDashboardResponse:
    if layout_type not in VALID_LAYOUT_TYPES:
        return CreateDashboardResponse(
            success=False,
            error=f"Invalid layout_type {layout_type!r}. Must be one of: {VALID_LAYOUT_TYPES}",
        )

    widget_error = _validate_known_widgets(widgets)
    if widget_error:
        return CreateDashboardResponse(success=False, error=widget_error)

    api_instance = get_api_instance(DashboardsApi, auth)

    try:
        dashboard_data: dict[str, Any] = {
            "title": title,
            "layout_type": layout_type,
            "widgets": widgets,
        }
        if description:
            dashboard_data["description"] = description
        if template_variables:
            dashboard_data["template_variables"] = template_variables
        if notify_list:
            dashboard_data["notify_list"] = notify_list
        if tags:
            dashboard_data["tags"] = tags

        response = api_instance.create_dashboard(body=Dashboard(**dashboard_data))

        return CreateDashboardResponse(
            dashboard_id=response.id, url=response.url, title=response.title or title
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(CreateDashboardResponse, e, required_scope="dashboards_write")


def _update_dashboard(
    dashboard_id: str,
    title: str | None,
    widgets: list[dict[str, Any]] | None,
    description: str | None,
    template_variables: list[dict[str, Any]] | None,
    layout_type: str | None,
    notify_list: list[str] | None,
    tags: list[str] | None,
    auth: DatadogAuth,
) -> UpdateDashboardResponse:
    if widgets is not None:
        widget_error = _validate_known_widgets(widgets)
        if widget_error:
            return UpdateDashboardResponse(success=False, error=widget_error)

    api_instance = get_api_instance(DashboardsApi, auth)

    try:
        existing_dict = _get_dashboard_json_dict(api_instance, dashboard_id)

        dashboard_data: dict[str, Any] = {
            "title": title or existing_dict.get("title"),
            "layout_type": layout_type or existing_dict.get("layout_type"),
            "widgets": widgets if widgets is not None else existing_dict.get("widgets", []),
        }
        for field, value in (
            ("description", description),
            ("template_variables", template_variables),
            ("notify_list", notify_list),
            ("tags", tags),
        ):
            if value is not None:
                dashboard_data[field] = value
            elif field in existing_dict:
                dashboard_data[field] = existing_dict[field]

        response = api_instance.update_dashboard(dashboard_id, body=Dashboard(**dashboard_data))

        return UpdateDashboardResponse(
            dashboard_id=response.id or dashboard_id,
            url=response.url,
            title=response.title or title,
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(UpdateDashboardResponse, e, required_scope="dashboards_write")


_WIDGET_TEMPLATES: dict[str, dict[str, Any]] = {
    "timeseries": {
        "definition": {
            "type": "timeseries",
            "title": "CPU usage over time",
            "requests": [{"q": "avg:system.cpu.user{*}", "display_type": "line"}],
        }
    },
    "query_value": {
        "definition": {
            "type": "query_value",
            "title": "Current error rate",
            "requests": [
                {"q": "sum:trace.web.request.errors{env:prod}.as_count()", "aggregator": "sum"}
            ],
        }
    },
    "toplist": {
        "definition": {
            "type": "toplist",
            "title": "Top 10 services by request count",
            "requests": [
                {"q": "top(sum:trace.web.request.hits{*} by {service}, 10, 'sum', 'desc')"}
            ],
        }
    },
    "heatmap": {
        "definition": {
            "type": "heatmap",
            "title": "Request latency distribution",
            "requests": [{"q": "avg:trace.web.request.duration{*} by {host}"}],
        }
    },
}


def register_dashboard_tools(mcp: FastMCP) -> None:
    """Register dashboard CRUD tools (no delete) and the widget-templates resource on `mcp`."""

    @mcp.resource("datadog://widget-templates")
    def widget_templates() -> str:
        """Ready-to-use widget definitions for `create_new_dashboard`/`update_existing_dashboard`.

        Covers the widget types most commonly requested (timeseries,
        query_value, toplist, heatmap). `timeseries`/`query_value`/`toplist`
        widgets are pre-flight validated server-side (missing `requests` or
        a `type` typo is rejected before the API call); other widget types
        are passed straight through to Datadog. See Datadog's dashboard
        widgets API documentation for the full list of ~40 widget types and
        every optional field.
        """
        return json.dumps(
            {
                "usage": (
                    "Each value below is a complete widget object - pass a list of these "
                    "(with your own query/title) as the `widgets` argument."
                ),
                "templates": _WIDGET_TEMPLATES,
            },
            indent=2,
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_all_dashboards(
        filter_query: str | None = None, limit: int = 100
    ) -> ListAllDashboardsResponse:
        """Browse all Datadog dashboards.

        Use this when: want to see what dashboards exist or find a specific dashboard.

        Args:
            filter_query: Search term to filter by name (case-insensitive substring match)
            limit: Max dashboards to return (default: 100)
        """
        return _list_dashboards(filter_query, limit, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def get_dashboard_details(dashboard_id: str) -> GetDashboardDetailsResponse:
        """Get complete dashboard configuration and widgets.

        Use this when: need to see what's in a dashboard or copy its configuration.
        Large dashboards may have their widget list truncated (see the `truncated`/
        `warning`/`total_available` fields) to stay within the response size budget.

        Args:
            dashboard_id: Dashboard ID from list_all_dashboards
        """
        return _get_dashboard(dashboard_id, get_auth_instance())

    @mcp.tool(annotations=WRITE_ADDITIVE)
    def create_new_dashboard(
        title: str,
        layout_type: str,
        widgets: list[dict[str, Any]],
        description: str | None = None,
        template_variables: list[dict[str, Any]] | None = None,
        notify_list: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> CreateDashboardResponse:
        """Create a new dashboard with custom widgets and layout.

        Use this when: user wants to visualize metrics, create a monitoring view, or track KPIs.
        See the datadog://widget-templates resource for ready-to-use widget definitions
        for the most common widget types (timeseries, query_value, toplist).

        Layout types:
        - "ordered": Timeline view (widgets stacked vertically)
        - "free": Free-form placement (drag anywhere)

        Args:
            title: Dashboard name
            layout_type: "ordered" or "free"
            widgets: Widget definitions (see datadog://widget-templates or Datadog API docs)
            description: Optional description
            template_variables: Optional filters/variables
            notify_list: Optional notification handles
            tags: Optional tags
        """
        return _create_dashboard(
            title,
            layout_type,
            widgets,
            description,
            template_variables,
            notify_list,
            tags,
            get_auth_instance(),
        )

    @mcp.tool(annotations=WRITE_OVERWRITE)
    def update_existing_dashboard(
        dashboard_id: str,
        title: str | None = None,
        widgets: list[dict[str, Any]] | None = None,
        description: str | None = None,
        template_variables: list[dict[str, Any]] | None = None,
        layout_type: str | None = None,
        notify_list: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> UpdateDashboardResponse:
        """Modify an existing dashboard. Overwrites the given fields; anything omitted is unchanged.

        Use this when: need to add widgets, change layout, or update dashboard config.
        There is no undo tool for dashboard updates - the previous widget/config state
        is not recoverable through this server once overwritten.

        Args:
            dashboard_id: Dashboard to update
            title: New title (optional)
            widgets: New widgets (optional, replaces the entire widget list)
            description: New description (optional)
            template_variables: New variables (optional)
            layout_type: New layout (optional)
            notify_list: New notification handles (optional)
            tags: New tags (optional)
        """
        return _update_dashboard(
            dashboard_id,
            title,
            widgets,
            description,
            template_variables,
            layout_type,
            notify_list,
            tags,
            get_auth_instance(),
        )
