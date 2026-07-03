"""Aggregation tools for efficient counting and summarizing without fetching raw data."""

from __future__ import annotations

from typing import Any, Literal

from datadog_api_client.v2.api.logs_api import LogsApi
from datadog_api_client.v2.model.logs_aggregate_request import LogsAggregateRequest
from datadog_api_client.v2.model.logs_aggregation_function import LogsAggregationFunction
from datadog_api_client.v2.model.logs_compute import LogsCompute
from datadog_api_client.v2.model.logs_compute_type import LogsComputeType
from datadog_api_client.v2.model.logs_group_by import LogsGroupBy
from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
from fastmcp import FastMCP
from pydantic import Field

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY
from ..utils.auth import get_api_instance
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    finalize_list_response,
    format_error_response,
)

AggregationName = Literal[
    "count", "cardinality", "pc75", "pc90", "pc95", "pc99", "sum", "min", "max", "avg"
]

_AGGREGATION_MAP: dict[AggregationName, LogsAggregationFunction] = {
    "count": LogsAggregationFunction.COUNT,
    "cardinality": LogsAggregationFunction.CARDINALITY,
    "pc75": LogsAggregationFunction.PERCENTILE_75,
    "pc90": LogsAggregationFunction.PERCENTILE_90,
    "pc95": LogsAggregationFunction.PERCENTILE_95,
    "pc99": LogsAggregationFunction.PERCENTILE_99,
    "sum": LogsAggregationFunction.SUM,
    "min": LogsAggregationFunction.MIN,
    "max": LogsAggregationFunction.MAX,
    "avg": LogsAggregationFunction.MEDIAN,  # closest available to a true average
}


class CountLogsResponse(ToolResponse):
    """Response for `count_logs`."""

    count: int = 0
    query: str | None = None
    from_time: str | None = None
    to_time: str | None = None


class CountUniqueValuesResponse(ToolResponse):
    """Response for `count_unique_values`."""

    unique_count: int = 0
    field: str | None = None
    query: str | None = None
    from_time: str | None = None
    to_time: str | None = None


class LogTimeseriesPoint(DatadogModel):
    """A single `{time, value}` point within a bucket's timeseries."""

    time: str | None = None
    value: float | None = None


class LogAggregationBucket(DatadogModel):
    """One group's result from `aggregate_logs_by_field`.

    Exactly one of `value` (scalar aggregation) or `timeseries` (when
    `interval` was requested) is populated, never both - this keeps the
    field fixed regardless of which aggregation function was requested,
    instead of the aggregation name becoming a dynamic dict key.
    """

    key: str | None = None
    value: float | None = None
    timeseries: list[LogTimeseriesPoint] = Field(default_factory=list)


class AggregateLogsResponse(PaginatedListResponse):
    """Response for `aggregate_logs_by_field`."""

    buckets: list[LogAggregationBucket] = Field(default_factory=list)
    group_by: str | None = None
    aggregation: str | None = None
    interval: str | None = None
    query: str | None = None
    from_time: str | None = None
    to_time: str | None = None


def _count_logs(
    query: str,
    from_time: str,
    to_time: str,
    indexes: list[str] | None,
    auth: DatadogAuth,
) -> CountLogsResponse:
    api_instance = get_api_instance(LogsApi, auth)

    try:
        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(aggregation=LogsAggregationFunction.COUNT, metric="*")],
        )
        response = api_instance.aggregate_logs(body=body)
        count = _extract_scalar(response, key="c0")

        return CountLogsResponse(
            count=int(count), query=query, from_time=from_time, to_time=to_time
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(CountLogsResponse, e, required_scope="logs_read")


def _count_unique(
    query: str,
    from_time: str,
    to_time: str,
    field: str,
    indexes: list[str] | None,
    auth: DatadogAuth,
) -> CountUniqueValuesResponse:
    api_instance = get_api_instance(LogsApi, auth)

    try:
        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(aggregation=LogsAggregationFunction.CARDINALITY, metric=field)],
        )
        response = api_instance.aggregate_logs(body=body)
        unique_count = _extract_scalar(response, key="c0")

        return CountUniqueValuesResponse(
            unique_count=int(unique_count),
            field=field,
            query=query,
            from_time=from_time,
            to_time=to_time,
        )

    except Exception as e:  # noqa: BLE001
        return format_error_response(CountUniqueValuesResponse, e, required_scope="logs_read")


def _extract_scalar(response: Any, key: str) -> float:
    """Sum a scalar compute value across all buckets (or read the single total)."""
    data = getattr(response, "data", None)
    if data is None:
        return 0.0

    buckets = getattr(data, "buckets", None)
    if buckets:
        return sum(float((bucket.computes or {}).get(key, 0) or 0) for bucket in buckets)

    attributes = getattr(data, "attributes", None)
    total = getattr(attributes, "total", None) if attributes else None
    if total is not None:
        return float(getattr(total, "count", None) or getattr(total, "aggregate_value", None) or 0)

    return 0.0


def _aggregate_logs_by_field(
    query: str,
    from_time: str,
    to_time: str,
    group_by: str,
    aggregation: AggregationName,
    metric: str | None,
    limit: int,
    indexes: list[str] | None,
    interval: str | None,
    auth: DatadogAuth,
) -> AggregateLogsResponse:
    api_instance = get_api_instance(LogsApi, auth)

    try:
        compute_kwargs: dict[str, Any] = {
            "aggregation": _AGGREGATION_MAP[aggregation],
            "metric": metric or "*",
        }
        if interval:
            compute_kwargs["type"] = LogsComputeType.TIMESERIES
            compute_kwargs["interval"] = interval

        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(**compute_kwargs)],
            group_by=[LogsGroupBy(facet=group_by, limit=limit)],
        )
        response = api_instance.aggregate_logs(body=body)

        buckets: list[LogAggregationBucket] = []
        raw_buckets = response.data.buckets if response.data and response.data.buckets else []
        for bucket in raw_buckets:
            key = (bucket.by or {}).get(group_by, "unknown") if bucket.by else "unknown"
            raw_value = (bucket.computes or {}).get("c0")

            if interval and isinstance(raw_value, list):
                points = [
                    LogTimeseriesPoint.model_validate(p.to_dict() if hasattr(p, "to_dict") else p)
                    for p in raw_value
                ]
                buckets.append(LogAggregationBucket(key=key, timeseries=points))
            else:
                buckets.append(LogAggregationBucket(key=key, value=float(raw_value or 0)))

        result = AggregateLogsResponse(
            buckets=buckets,
            group_by=group_by,
            aggregation=aggregation,
            interval=interval,
            query=query,
            from_time=from_time,
            to_time=to_time,
        )
        return finalize_list_response(result, "buckets")

    except Exception as e:  # noqa: BLE001
        return format_error_response(AggregateLogsResponse, e, required_scope="logs_read")


def register_aggregation_tools(mcp: FastMCP) -> None:
    """Register `count_logs`, `count_unique_values`, and `aggregate_logs_by_field` on `mcp`."""

    @mcp.tool(annotations=READ_ONLY)
    def count_logs(
        query: str, from_time: str, to_time: str, indexes: list[str] | None = None
    ) -> CountLogsResponse:
        """Count logs matching a query WITHOUT fetching all data (fast & lightweight).

        PREFERRED for counting events - much faster than search_logs, which
        should never be used just to count results.

        Use this when:
        - "How many errors happened?"
        - "Count logs for a service"
        - Need a number, not log content

        Examples:
            count_logs("status:error", "now-1h", "now") -> {"count": 45, ...}

        Args:
            query: Search query using Datadog log search syntax (e.g. "status:error service:api")
            from_time: Start time - ISO 8601, relative date math (e.g. "now-1h"), or a
                millisecond timestamp
            to_time: End time - same accepted formats as from_time
            indexes: Optional list of index names to search (e.g. ["main", "retention"])
        """
        return _count_logs(query, from_time, to_time, indexes, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def count_unique_values(
        query: str, from_time: str, to_time: str, field: str, indexes: list[str] | None = None
    ) -> CountUniqueValuesResponse:
        """Count UNIQUE values of a field (distinct count / cardinality).

        PERFECT for counting unique sessions, users, IPs, etc. Much more
        efficient than fetching all logs with search_logs and counting
        distinct values client-side.

        Use this when:
        - "How many unique users/sessions?"
        - "Count distinct values"
        - "How many different X?"

        Examples:
            count_unique_values("service:api", "now-1d", "now", "@session_id")
            -> {"unique_count": 150, ...}

        Args:
            query: Search query using Datadog log search syntax
            from_time: Start time - ISO 8601, relative date math (e.g. "now-1h"), or a
                millisecond timestamp
            to_time: End time - same accepted formats as from_time
            field: Field to count unique values of (e.g. "@session_id", "@user.id", "host")
            indexes: Optional list of index names to search
        """
        return _count_unique(query, from_time, to_time, field, indexes, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def aggregate_logs_by_field(
        query: str,
        from_time: str,
        to_time: str,
        group_by: str,
        aggregation: AggregationName = "count",
        metric: str | None = None,
        limit: int = 10,
        indexes: list[str] | None = None,
        interval: str | None = None,
    ) -> AggregateLogsResponse:
        """Aggregate and group logs by a field with statistics (fast, no raw data transfer).

        PERFECT for analytics, charts, and dashboards. Set `interval` to get a
        timeseries per group instead of a single scalar per group - this
        covers timeseries use cases without needing a separate tool.

        Use this when:
        - "Group errors by service"
        - "Top 10 services by request count"
        - "Average duration per endpoint, per hour" (set interval="1h")

        Examples:
            aggregate_logs_by_field("service:api", "now-1d", "now", "status", "count")
            -> top statuses with counts
            aggregate_logs_by_field("service:api", "now-1d", "now", "status", "count", interval="1h")
            -> counts per status, bucketed hourly

        Args:
            query: Search query using Datadog log search syntax
            from_time: Start time - ISO 8601, relative date math (e.g. "now-1h"), or a
                millisecond timestamp
            to_time: End time - same accepted formats as from_time
            group_by: Field to group by (e.g. "@airline_name", "service", "status")
            aggregation: Aggregation function to apply within each group
            metric: Metric field for aggregations other than count (e.g. "@duration" for avg)
            limit: Maximum number of groups to return (default: 10)
            indexes: Optional list of index names to search
            interval: If set (e.g. "5m", "1h", "1d"), returns a timeseries per group
                instead of a single scalar per group
        """
        return _aggregate_logs_by_field(
            query,
            from_time,
            to_time,
            group_by,
            aggregation,
            metric,
            limit,
            indexes,
            interval,
            get_auth_instance(),
        )
