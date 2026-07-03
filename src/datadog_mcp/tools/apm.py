"""APM tools for searching traces/spans and aggregating performance data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from datadog_api_client.v2.api.apm_trace_api import APMTraceApi
from datadog_api_client.v2.api.spans_api import SpansApi
from datadog_api_client.v2.model.spans_list_request import SpansListRequest
from datadog_api_client.v2.model.spans_list_request_attributes import SpansListRequestAttributes
from datadog_api_client.v2.model.spans_list_request_data import SpansListRequestData
from datadog_api_client.v2.model.spans_list_request_page import SpansListRequestPage
from datadog_api_client.v2.model.spans_list_request_type import SpansListRequestType
from datadog_api_client.v2.model.spans_query_filter import SpansQueryFilter
from datadog_api_client.v2.model.spans_sort import SpansSort
from fastmcp import FastMCP
from pydantic import Field, model_validator

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY
from ..utils.auth import get_api_instance
from ..utils.pagination import DEFAULT_PAGE_SIZE, clamp_page_size
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    finalize_list_response,
    format_error_response,
)


class SpanEntry(DatadogModel):
    """A single span, flattened from Datadog's `{id, type, attributes}` envelope.

    NOTE ON FIELD ACCURACY: `datadog_api_client`'s `SpansAttributes` model
    (the unified Spans product, not the legacy Traces API) does not expose
    `operation_name`/`duration`/`start` fields the way older APM tooling
    assumes. This model reads the real field names (`start_timestamp`,
    `end_timestamp`, `resource_name`) and derives `duration_ns` from the two
    timestamps; `operation` is a best-effort read from the open `custom`
    attributes bag, which may not be populated for every span.
    """

    id: str | None = None
    trace_id: str | None = None
    parent_id: str | None = None
    service: str | None = None
    resource: str | None = None
    operation: str | None = None
    env: str | None = None
    host: str | None = None
    start: str | None = None
    end: str | None = None
    duration_ns: float | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _flatten_datadog_envelope(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("attributes"), dict):
            return data

        attrs = data["attributes"]
        custom = attrs.get("custom") or {}
        start = attrs.get("start_timestamp")
        end = attrs.get("end_timestamp")
        duration_ns = None
        if start and end:
            try:
                duration_ns = (
                    datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                    - datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                ).total_seconds() * 1_000_000_000
            except ValueError:
                duration_ns = None

        return {
            "id": data.get("id"),
            "trace_id": attrs.get("trace_id"),
            "parent_id": attrs.get("parent_id"),
            "service": attrs.get("service"),
            "resource": attrs.get("resource_name"),
            "operation": custom.get("operation_name") or custom.get("name"),
            "env": attrs.get("env"),
            "host": attrs.get("host"),
            "start": start,
            "end": end,
            "duration_ns": duration_ns,
            "tags": attrs.get("tags") or [],
        }


class SearchApmTracesResponse(PaginatedListResponse):
    """Response for `search_apm_traces`."""

    spans: list[SpanEntry] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class TraceSpanEntry(DatadogModel):
    """One span within a trace, from `get_full_trace`.

    This is a deliberately different shape from `SpanEntry` (used by
    `search_apm_traces`): it mirrors Datadog's dedicated per-trace endpoint
    (`APMTraceApi.get_trace_by_id`), which represents span/trace/parent ids
    as integers and nests tag-like data under `meta`/`metrics` rather than
    the `custom` bag the Spans search product uses.
    """

    span_id: int | None = None
    trace_id: int | None = None
    parent_id: int | None = None
    service: str | None = None
    name: str | None = None
    resource: str | None = None
    type: str | None = None
    start_time: int | None = None
    end_time: int | None = None
    duration_ns: int | None = None
    self_time_ns: float | None = None
    is_error: bool = False
    meta: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_field_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "duration" in normalized:
            normalized["duration_ns"] = normalized.pop("duration")
        if "self_time" in normalized:
            normalized["self_time_ns"] = normalized.pop("self_time")
        if "error" in normalized:
            normalized["is_error"] = bool(normalized.pop("error"))
        return normalized


class GetFullTraceResponse(PaginatedListResponse):
    """Response for `get_full_trace`."""

    spans: list[TraceSpanEntry] = Field(default_factory=list)
    trace_id: str | None = None
    root_span: TraceSpanEntry | None = None
    total_duration_ns: int | None = None
    is_truncated: bool = False


class ListApmServicesResponse(PaginatedListResponse):
    """Response for `list_apm_services`."""

    services: list[str] = Field(default_factory=list)
    environment: str | None = None


class SpanAggregationBucket(DatadogModel):
    """One group's result from `aggregate_spans`."""

    key: str | None = None
    value: float | None = None


class AggregateSpansResponse(PaginatedListResponse):
    """Response for `aggregate_spans`."""

    buckets: list[SpanAggregationBucket] = Field(default_factory=list)
    group_by: str | None = None
    aggregation: str | None = None
    query: str | None = None
    from_time: str | None = None
    to_time: str | None = None


def _search_spans(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int,
    cursor: str | None,
    sort: str,
    auth: DatadogAuth,
) -> SearchApmTracesResponse:
    page_size = clamp_page_size(page_size)
    api_instance = get_api_instance(SpansApi, auth)

    try:
        page_config = SpansListRequestPage(limit=page_size)
        if cursor:
            page_config.cursor = cursor

        body = SpansListRequest(
            data=SpansListRequestData(
                attributes=SpansListRequestAttributes(
                    filter=SpansQueryFilter(
                        query=query,
                        **{"from": from_time, "to": to_time},
                    ),
                    page=page_config,
                    sort=SpansSort(sort),  # type: ignore[no-untyped-call]
                ),
                type=SpansListRequestType("search_request"),  # type: ignore[no-untyped-call]
            )
        )

        response = api_instance.list_spans(body=body)
        spans = [SpanEntry.model_validate(span.to_dict()) for span in (response.data or [])]

        next_cursor: str | None = None
        has_more = False
        page = getattr(response.meta, "page", None) if response.meta else None
        if page is not None and getattr(page, "after", None):
            next_cursor = page.after
            has_more = True

        result = SearchApmTracesResponse(spans=spans, next_cursor=next_cursor, has_more=has_more)
        return finalize_list_response(result, "spans")

    except Exception as e:  # noqa: BLE001
        return format_error_response(SearchApmTracesResponse, e, required_scope="apm_read")


def _get_trace(trace_id: str, auth: DatadogAuth) -> GetFullTraceResponse:
    # Uses the dedicated per-trace endpoint (APMTraceApi.get_trace_by_id),
    # not a span search - this is the correct "get one trace by ID" call in
    # datadog-api-client 2.57 (the v2 "TracesApi" some older tooling assumes
    # does not exist in this client version).
    api_instance = get_api_instance(APMTraceApi, auth)

    try:
        response = api_instance.get_trace_by_id(trace_id)
        attributes = response.data.attributes if response.data else None
        raw_spans = attributes.spans if attributes else []
        spans = [
            TraceSpanEntry.model_validate(s.to_dict())  # type: ignore[no-untyped-call]
            for s in (raw_spans or [])
        ]

        if not spans:
            return GetFullTraceResponse(success=False, error=f"No trace found with ID: {trace_id}")

        root_span = next((s for s in spans if s.parent_id is None), None)
        total_duration = max((s.duration_ns or 0 for s in spans), default=0)

        result = GetFullTraceResponse(
            spans=spans,
            trace_id=trace_id,
            root_span=root_span,
            total_duration_ns=total_duration,
            is_truncated=bool(attributes.is_truncated) if attributes else False,
        )
        return finalize_list_response(result, "spans")

    except Exception as e:  # noqa: BLE001
        return format_error_response(GetFullTraceResponse, e, required_scope="apm_read")


def _list_services(env: str | None, limit: int, auth: DatadogAuth) -> ListApmServicesResponse:
    api_instance = get_api_instance(SpansApi, auth)

    try:
        query = f"env:{env}" if env else "*"
        response = api_instance.aggregate_spans(
            body={  # type: ignore[arg-type]
                "data": {
                    "type": "aggregate_request",
                    "attributes": {
                        "filter": {"query": query, "from": "now-1h", "to": "now"},
                        "compute": [{"aggregation": "count"}],
                        "group_by": [{"facet": "service"}],
                    },
                }
            }
        )

        services: list[str] = []
        for bucket in (response.data or [])[:limit]:
            by = getattr(bucket.attributes, "by", None) if bucket.attributes else None
            if by and "service" in by:
                services.append(by["service"])

        result = ListApmServicesResponse(services=services, environment=env)
        return finalize_list_response(result, "services")

    except Exception as e:  # noqa: BLE001
        return format_error_response(ListApmServicesResponse, e, required_scope="apm_read")


def _aggregate_spans(
    query: str,
    from_time: str,
    to_time: str,
    group_by: str,
    aggregation: str,
    metric: str | None,
    limit: int,
    auth: DatadogAuth,
) -> AggregateSpansResponse:
    api_instance = get_api_instance(SpansApi, auth)

    try:
        compute: dict[str, Any] = {"aggregation": aggregation}
        if metric:
            compute["metric"] = metric

        response = api_instance.aggregate_spans(
            body={  # type: ignore[arg-type]
                "data": {
                    "type": "aggregate_request",
                    "attributes": {
                        "filter": {
                            "query": query,
                            **{"from": from_time, "to": to_time},
                        },
                        "compute": [compute],
                        "group_by": [{"facet": group_by, "limit": limit}],
                    },
                }
            }
        )

        buckets: list[SpanAggregationBucket] = []
        for bucket in response.data or []:
            attrs = bucket.attributes
            by = getattr(attrs, "by", None) if attrs else None
            computes = getattr(attrs, "computes", None) if attrs else None
            key = by.get(group_by, "unknown") if by else "unknown"
            value = (computes or {}).get("c0")
            buckets.append(SpanAggregationBucket(key=key, value=float(value or 0)))

        result = AggregateSpansResponse(
            buckets=buckets,
            group_by=group_by,
            aggregation=aggregation,
            query=query,
            from_time=from_time,
            to_time=to_time,
        )
        return finalize_list_response(result, "buckets")

    except Exception as e:  # noqa: BLE001
        return format_error_response(AggregateSpansResponse, e, required_scope="apm_read")


def register_apm_tools(mcp: FastMCP) -> None:
    """Register APM search, trace, service, and aggregation tools on `mcp`."""

    @mcp.tool(annotations=READ_ONLY)
    def search_apm_traces(
        query: str,
        from_time: str,
        to_time: str,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        sort: str = "timestamp",
    ) -> SearchApmTracesResponse:
        """Search distributed traces and spans for performance analysis (paginated).

        Use this when: debugging slow requests, finding errors in services, or analyzing latency.
        For statistics (latency percentiles, error rates) without fetching raw spans,
        use aggregate_spans instead - it is much lighter for dashboards/analytics.

        Common queries:
        - Find errors: "service:api @error.message:*"
        - By status: "service:checkout @http.status_code:500"
        - Custom tags: "@airline_name:aeromexico @session_id:*"

        Args:
            query: Search query using Datadog APM span search syntax (examples above)
            from_time: Start time - ISO 8601, relative date math (e.g. "now-1h"), or a
                millisecond timestamp
            to_time: End time - same accepted formats as from_time
            page_size: Spans per page (default: 25, max: 50)
            cursor: Pagination cursor from a previous response
            sort: "timestamp" or "-timestamp"
        """
        return _search_spans(
            query, from_time, to_time, page_size, cursor, sort, get_auth_instance()
        )

    @mcp.tool(annotations=READ_ONLY)
    def get_full_trace(trace_id: str) -> GetFullTraceResponse:
        """Get complete trace with all spans and timing information.

        Use this when: need to see full request flow across services (after finding a trace ID).

        Args:
            trace_id: Trace identifier from search results
        """
        return _get_trace(trace_id, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def list_apm_services(env: str | None = None, limit: int = 100) -> ListApmServicesResponse:
        """List services sending APM data in the last hour.

        Use this when: want to see what services are instrumented or find service names.

        Args:
            env: Filter by environment (e.g. "prod", "staging")
            limit: Max services to return (default: 100)
        """
        return _list_services(env, limit, get_auth_instance())

    @mcp.tool(annotations=READ_ONLY)
    def aggregate_spans(
        query: str,
        from_time: str,
        to_time: str,
        group_by: str,
        aggregation: str = "count",
        metric: str | None = None,
        limit: int = 10,
    ) -> AggregateSpansResponse:
        """Aggregate spans by a field for latency/error statistics (no raw span data transfer).

        PERFECT for "what's slow" or "what's erroring" questions without paying the
        cost of fetching and reading raw spans with search_apm_traces.

        Use this when:
        - "p95 latency by service"
        - "Error count by endpoint"
        - "Average duration per operation"

        Examples:
            aggregate_spans("service:checkout", "now-1h", "now", "resource_name", "pc95", "@duration")
            -> p95 duration per resource

        Args:
            query: Search query using Datadog APM span search syntax
            from_time: Start time - ISO 8601, relative date math (e.g. "now-1h"), or a
                millisecond timestamp
            to_time: End time - same accepted formats as from_time
            group_by: Facet to group by (e.g. "service", "resource_name", "@http.status_code")
            aggregation: Aggregation function - count, avg, cardinality, median, pc75, pc90,
                pc95, pc98, pc99, sum, min, max
            metric: Field to aggregate for non-count aggregations (e.g. "@duration")
            limit: Maximum number of groups to return (default: 10)
        """
        return _aggregate_spans(
            query, from_time, to_time, group_by, aggregation, metric, limit, get_auth_instance()
        )
