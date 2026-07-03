"""Metrics tools for querying, discovering, and submitting Datadog metrics."""

from __future__ import annotations

from typing import Any

from datadog_api_client.v1.api.metrics_api import MetricsApi
from datadog_api_client.v2.api.metrics_api import MetricsApi as MetricsApiV2
from datadog_api_client.v2.model.metric_intake_type import MetricIntakeType
from datadog_api_client.v2.model.metric_payload import MetricPayload
from datadog_api_client.v2.model.metric_point import MetricPoint
from datadog_api_client.v2.model.metric_series import MetricSeries
from fastmcp import FastMCP
from pydantic import Field

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY, WRITE_ADDITIVE
from ..utils.auth import get_api_instance
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    finalize_list_response,
    format_error_response,
)
from ..utils.time import parse_time_value


class MetricSeriesEntry(DatadogModel):
    """One metric time series from `query_metrics`."""

    metric: str | None = None
    display_name: str | None = None
    unit: str | None = None
    pointlist: list[list[float | None]] = Field(default_factory=list)
    scope: str | None = None
    interval: float | None = None
    aggr: str | None = None
    expression: str | None = None


class QueryMetricsResponse(PaginatedListResponse):
    """Response for `query_metrics`."""

    series: list[MetricSeriesEntry] = Field(default_factory=list)
    query: str | None = None
    from_date: int | None = None
    to_date: int | None = None


class ListAvailableMetricsResponse(PaginatedListResponse):
    """Response for `list_available_metrics`."""

    metrics: list[str] = Field(default_factory=list)


class SendCustomMetricResponse(ToolResponse):
    """Response for `send_custom_metric`."""

    metric_name: str | None = None
    points_submitted: int = 0
    status: str | None = None


class ListActiveMetricsResponse(PaginatedListResponse):
    """Response for `list_active_metrics`."""

    metrics: list[str] = Field(default_factory=list)
    from_time: str | int | None = None


class DescribeMetricResponse(ToolResponse):
    """Response for `describe_metric` (consolidates metadata + tag discovery)."""

    metric_name: str | None = None
    description: str | None = None
    type: str | None = None
    unit: str | None = None
    per_unit: str | None = None
    short_name: str | None = None
    integration: str | None = None
    tags: list[str] = Field(default_factory=list)
    ingested_tags: list[str] = Field(default_factory=list)


def _query_metrics(
    query: str, from_time: int | str, to_time: int | str, auth: DatadogAuth
) -> QueryMetricsResponse:
    api_instance = get_api_instance(MetricsApi, auth)
    resolved_from = parse_time_value(from_time)
    resolved_to = parse_time_value(to_time)

    try:
        response = api_instance.query_metrics(_from=resolved_from, to=resolved_to, query=query)

        series = [MetricSeriesEntry.model_validate(s.to_dict()) for s in (response.series or [])]

        result = QueryMetricsResponse(
            series=series,
            query=query,
            from_date=response.from_date if response.from_date is not None else resolved_from,
            to_date=response.to_date if response.to_date is not None else resolved_to,
        )
        return finalize_list_response(result, "series")

    except Exception as e:  # noqa: BLE001
        return format_error_response(QueryMetricsResponse, e, required_scope="metrics_read")


def _list_metrics(
    filter: str | None, limit: int, auth: DatadogAuth
) -> ListAvailableMetricsResponse:
    api_instance = get_api_instance(MetricsApi, auth)

    try:
        response = api_instance.list_metrics(q=filter or "*")
        metrics = list((response.metrics or [])[:limit])

        result = ListAvailableMetricsResponse(metrics=metrics)
        return finalize_list_response(result, "metrics")

    except Exception as e:  # noqa: BLE001
        return format_error_response(ListAvailableMetricsResponse, e, required_scope="metrics_read")


def _submit_metrics(
    metric_name: str,
    points: list[tuple[int, float]],
    metric_type: str,
    tags: list[str] | None,
    host: str | None,
    interval: int | None,
    auth: DatadogAuth,
) -> SendCustomMetricResponse:
    type_mapping = {
        "gauge": MetricIntakeType(0),  # type: ignore[no-untyped-call]
        "count": MetricIntakeType(1),  # type: ignore[no-untyped-call]
        "rate": MetricIntakeType(2),  # type: ignore[no-untyped-call]
    }
    if metric_type not in type_mapping:
        return SendCustomMetricResponse(
            success=False,
            error=f"Invalid metric_type {metric_type!r}. Must be one of: {list(type_mapping)}",
        )

    api_instance = get_api_instance(MetricsApiV2, auth)

    try:
        metric_points = [MetricPoint(timestamp=int(ts), value=float(val)) for ts, val in points]

        series_kwargs: dict[str, Any] = {
            "metric": metric_name,
            "type": type_mapping[metric_type],
            "points": metric_points,
        }
        if tags:
            series_kwargs["tags"] = tags
        if host:
            series_kwargs["resources"] = [{"name": host, "type": "host"}]
        if interval:
            series_kwargs["interval"] = interval

        series = MetricSeries(**series_kwargs)

        response = api_instance.submit_metrics(body=MetricPayload(series=[series]))
        status = getattr(response, "status", None)

        return SendCustomMetricResponse(
            metric_name=metric_name, points_submitted=len(points), status=status
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(SendCustomMetricResponse, e, required_scope="metrics_write")


def _list_active_metrics(
    since: int | str, host: str | None, tag_filter: str | None, auth: DatadogAuth
) -> ListActiveMetricsResponse:
    api_instance = get_api_instance(MetricsApi, auth)
    resolved_since = parse_time_value(since)

    try:
        kwargs: dict[str, str] = {}
        if host:
            kwargs["host"] = host
        if tag_filter:
            kwargs["tag_filter"] = tag_filter

        response = api_instance.list_active_metrics(_from=resolved_since, **kwargs)
        metrics = list(response.metrics or [])

        result = ListActiveMetricsResponse(metrics=metrics, from_time=since)
        return finalize_list_response(result, "metrics")

    except Exception as e:  # noqa: BLE001
        return format_error_response(ListActiveMetricsResponse, e, required_scope="metrics_read")


def _describe_metric(metric_name: str, auth: DatadogAuth) -> DescribeMetricResponse:
    metrics_v1 = get_api_instance(MetricsApi, auth)
    metrics_v2 = get_api_instance(MetricsApiV2, auth)

    try:
        metadata = metrics_v1.get_metric_metadata(metric_name)
    except Exception as e:  # noqa: BLE001
        return format_error_response(DescribeMetricResponse, e, required_scope="metrics_read")

    result = DescribeMetricResponse(
        metric_name=metric_name,
        description=metadata.description,
        type=str(metadata.type) if metadata.type else None,
        unit=metadata.unit,
        per_unit=metadata.per_unit,
        short_name=metadata.short_name,
        integration=metadata.integration,
    )

    # Tag discovery is best-effort: some metrics genuinely have no tags, and
    # this call has occasionally needed a wider scope than plain metadata in
    # other Datadog accounts, so a failure here shouldn't hide the metadata
    # we already have.
    try:
        tags_response = metrics_v2.list_tags_by_metric_name(metric_name)
        attributes = tags_response.data.attributes if tags_response.data else None
        if attributes is not None:
            result.tags = list(attributes.tags or [])
            result.ingested_tags = list(attributes.ingested_tags or [])
    except Exception as e:  # noqa: BLE001
        result.error = f"Metadata succeeded but tag discovery failed: {e}"

    return result


def register_metrics_tools(mcp: FastMCP) -> None:
    """Register metrics tools on `mcp`: query, discovery, and submission."""

    @mcp.tool(annotations=READ_ONLY)
    def query_metrics(query: str, from_time: int | str, to_time: int | str) -> QueryMetricsResponse:
        """Query and visualize time series metrics.

        Use this when: need to check system performance, resource usage, or custom metrics.

        Common queries:
        - CPU: "avg:system.cpu.user{*}"
        - Memory: "avg:system.mem.used{*}"
        - By host: "avg:system.load.1{host:web-01}"
        - By tag: "sum:requests.count{env:prod}"

        Args:
            query: Metric query in Datadog syntax (examples above)
            from_time: Start time - Unix timestamp (seconds), relative date math
                (e.g. "now-4h"), or an ISO 8601 datetime string
            to_time: End time - same accepted formats as from_time
        """
        return _query_metrics(query, from_time, to_time, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def list_available_metrics(
        filter: str | None = None, limit: int = 100
    ) -> ListAvailableMetricsResponse:
        """List all metrics available in Datadog.

        Use this when: don't know the exact metric name, or want to discover what's available.
        For metric metadata (description, unit, type) and tags on a specific metric,
        use describe_metric instead.

        Args:
            filter: Search term (e.g. "cpu", "memory", "docker")
            limit: Max metrics to return (default: 100)
        """
        return _list_metrics(filter, limit, get_auth_instance())

    @mcp.tool(annotations=WRITE_ADDITIVE)
    def send_custom_metric(
        metric_name: str,
        points: list[tuple[int, float]],
        metric_type: str = "gauge",
        tags: list[str] | None = None,
        host: str | None = None,
        interval: int | None = None,
    ) -> SendCustomMetricResponse:
        """Send custom metric data points to Datadog.

        Use this when: need to track custom application metrics or business KPIs.

        Metric types:
        - gauge: Point-in-time value (temperature, queue size)
        - count: Count of events in interval
        - rate: Events per second

        Args:
            metric_name: Your metric name (e.g. "app.users.active")
            points: [(timestamp, value), ...] where timestamp is Unix seconds
            metric_type: "gauge", "count", or "rate"
            tags: Optional tags (e.g. ["env:prod", "region:us"])
            host: Optional hostname
            interval: Seconds between points (for count/rate)
        """
        return _submit_metrics(
            metric_name, points, metric_type, tags, host, interval, get_auth_instance()
        )

    @mcp.tool(annotations=READ_ONLY)
    def list_active_metrics(
        since: int | str = "now-1h", host: str | None = None, tag_filter: str | None = None
    ) -> ListActiveMetricsResponse:
        """List metrics that have reported data since a given time.

        Use this when: you want to know what's actually emitting data recently,
        as opposed to list_available_metrics which lists every metric name Datadog
        knows about (including ones that stopped reporting long ago).

        Args:
            since: Only include metrics with data since this time - Unix timestamp
                (seconds), relative date math (e.g. "now-1h"), or an ISO 8601
                datetime string (default: "now-1h")
            host: Optional hostname filter
            tag_filter: Optional tag filter (e.g. "env:prod")
        """
        return _list_active_metrics(since, host, tag_filter, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def describe_metric(metric_name: str) -> DescribeMetricResponse:
        """Get metadata (description, unit, type) and known tags for a metric.

        Use this when: you need to understand what a metric means or what tags
        you can group/filter by before writing a query_metrics or monitor query.
        Consolidates metric metadata and tag discovery into a single call.

        Args:
            metric_name: Exact metric name (e.g. "system.cpu.user"), as returned by
                list_available_metrics or list_active_metrics
        """
        return _describe_metric(metric_name, get_auth_instance())
