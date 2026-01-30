"""Aggregation tools for efficient counting and summarizing without fetching raw data."""

from typing import Literal

from datadog_api_client.v2.api.logs_api import LogsApi
from datadog_api_client.v2.model.logs_aggregate_request import LogsAggregateRequest
from datadog_api_client.v2.model.logs_aggregation_function import LogsAggregationFunction
from datadog_api_client.v2.model.logs_compute import LogsCompute
from datadog_api_client.v2.model.logs_group_by import LogsGroupBy
from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter

from ..auth import DatadogAuth
from ..utils.auth import get_api_instance


def count_logs(
    query: str,
    from_time: str,
    to_time: str,
    indexes: list[str] | None = None,
    auth: DatadogAuth | None = None,
) -> dict:
    """Count logs matching a query without fetching all data.

    This is much faster and lighter than search_logs when you only need a count.

    Args:
        query: Search query using Datadog log search syntax (e.g., "status:error service:api")
        from_time: Start time (ISO 8601, date math like "now-1h", or timestamp ms)
        to_time: End time (ISO 8601, date math like "now", or timestamp ms)
        indexes: Optional list of index names to search (e.g., ["main", "retention"])
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: {"success": bool, "count": int, "query": str}

    Example:
        count_logs("status:error env:prod", "now-1h", "now")
        -> {"success": true, "count": 1234, "query": "status:error env:prod"}
    """
    api_instance, auth = get_api_instance(LogsApi, auth)

    try:
        # Build aggregate request with count computation
        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(aggregation=LogsAggregationFunction.COUNT, metric="*")],
        )

        response = api_instance.aggregate_logs(body=body)

        # Extract count from response
        count = 0
        if hasattr(response, "data") and response.data:
            if hasattr(response.data, "buckets") and response.data.buckets:
                # If there are buckets, sum all counts
                for bucket in response.data.buckets:
                    if hasattr(bucket, "computes") and bucket.computes:
                        count += bucket.computes.get("c0", 0)
            elif hasattr(response.data, "attributes") and hasattr(
                response.data.attributes, "total"
            ):
                # If no buckets, use total
                count = (
                    response.data.attributes.total.count
                    if hasattr(response.data.attributes.total, "count")
                    else 0
                )

        return {"success": True, "count": count, "query": query, "from": from_time, "to": to_time}

    except Exception as e:
        return {"success": False, "error": str(e), "count": 0}


def count_unique(
    query: str,
    from_time: str,
    to_time: str,
    field: str,
    indexes: list[str] | None = None,
    auth: DatadogAuth | None = None,
) -> dict:
    """Count unique values of a field (cardinality) without fetching all data.

    Perfect for counting unique users, sessions, IPs, etc. Much more efficient than
    fetching all logs and counting unique values locally.

    Args:
        query: Search query using Datadog log search syntax
        from_time: Start time (ISO 8601, date math like "now-1h", or timestamp ms)
        to_time: End time (ISO 8601, date math like "now", or timestamp ms)
        field: Field to count unique values (e.g., "@session_id", "@user.id", "host")
        indexes: Optional list of index names to search
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: {"success": bool, "unique_count": int, "field": str, "query": str}

    Example:
        count_unique("service:omni-channel airline:aeromexico", "now-1d", "now", "@session_id")
        -> {"success": true, "unique_count": 150, "field": "@session_id"}
    """
    api_instance, auth = get_api_instance(LogsApi, auth)

    try:
        # Build aggregate request with cardinality computation
        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(aggregation=LogsAggregationFunction.CARDINALITY, metric=field)],
        )

        response = api_instance.aggregate_logs(body=body)

        # Extract cardinality from response
        unique_count = 0
        if hasattr(response, "data") and response.data:
            if hasattr(response.data, "buckets") and response.data.buckets:
                # If there are buckets, sum all cardinalities
                for bucket in response.data.buckets:
                    if hasattr(bucket, "computes") and bucket.computes:
                        unique_count += bucket.computes.get("c0", 0)
            elif hasattr(response.data, "attributes") and hasattr(
                response.data.attributes, "total"
            ):
                # If no buckets, use total
                if hasattr(response.data.attributes.total, "aggregate_value"):
                    unique_count = response.data.attributes.total.aggregate_value

        return {
            "success": True,
            "unique_count": unique_count,
            "field": field,
            "query": query,
            "from": from_time,
            "to": to_time,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "unique_count": 0}


def aggregate_logs(
    query: str,
    from_time: str,
    to_time: str,
    group_by: str,
    aggregation: Literal[
        "count", "cardinality", "pc75", "pc90", "pc95", "pc99", "sum", "min", "max", "avg"
    ] = "count",
    metric: str | None = None,
    limit: int = 10,
    indexes: list[str] | None = None,
    auth: DatadogAuth | None = None,
) -> dict:
    """Aggregate logs by a field with various aggregation functions.

    This allows you to group and aggregate logs efficiently without fetching raw data.
    Perfect for dashboards, charts, and analytics.

    Args:
        query: Search query using Datadog log search syntax
        from_time: Start time (ISO 8601, date math like "now-1h", or timestamp ms)
        to_time: End time (ISO 8601, date math like "now", or timestamp ms)
        group_by: Field to group by (e.g., "@airline_name", "service", "status")
        aggregation: Aggregation function - count, cardinality, pc75, pc90, pc95, pc99, sum, min, max, avg
        metric: Metric field for aggregations other than count (e.g., "@duration" for avg)
        limit: Maximum number of groups to return (default: 10)
        indexes: Optional list of index names to search
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: {"success": bool, "buckets": [{"key": str, "value": number}, ...], "total": int}

    Example:
        aggregate_logs("service:omni-channel", "now-1d", "now", "@airline_name", "count")
        -> {"success": true, "buckets": [{"key": "aeromexico", "count": 50}, {"key": "volaris", "count": 30}]}
    """
    api_instance, auth = get_api_instance(LogsApi, auth)

    try:
        # Map string aggregation to enum
        agg_map = {
            "count": LogsAggregationFunction.COUNT,
            "cardinality": LogsAggregationFunction.CARDINALITY,
            "pc75": LogsAggregationFunction.PERCENTILE_75,
            "pc90": LogsAggregationFunction.PERCENTILE_90,
            "pc95": LogsAggregationFunction.PERCENTILE_95,
            "pc99": LogsAggregationFunction.PERCENTILE_99,
            "sum": LogsAggregationFunction.SUM,
            "min": LogsAggregationFunction.MIN,
            "max": LogsAggregationFunction.MAX,
            "avg": LogsAggregationFunction.MEDIAN,  # Using median as closest to avg
        }

        agg_function = agg_map.get(aggregation, LogsAggregationFunction.COUNT)
        compute_metric = metric if metric else "*"

        # Build aggregate request with grouping
        body = LogsAggregateRequest(
            filter=LogsQueryFilter(
                query=query,
                **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
                indexes=indexes or ["*"],
            ),
            compute=[LogsCompute(aggregation=agg_function, metric=compute_metric)],
            group_by=[LogsGroupBy(facet=group_by, limit=limit)],
        )

        response = api_instance.aggregate_logs(body=body)

        # Extract buckets from response
        buckets = []
        total = 0

        if hasattr(response, "data") and response.data:
            if hasattr(response.data, "buckets") and response.data.buckets:
                for bucket in response.data.buckets:
                    bucket_entry = {}

                    # Extract group key
                    if hasattr(bucket, "by") and bucket.by:
                        bucket_entry["key"] = bucket.by.get(group_by, "unknown")

                    # Extract computed value
                    if hasattr(bucket, "computes") and bucket.computes:
                        value = bucket.computes.get("c0", 0)
                        bucket_entry[aggregation] = value
                        total += value if aggregation == "count" else 1

                    buckets.append(bucket_entry)

        return {
            "success": True,
            "buckets": buckets,
            "total_buckets": len(buckets),
            "group_by": group_by,
            "aggregation": aggregation,
            "query": query,
            "from": from_time,
            "to": to_time,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "buckets": []}
