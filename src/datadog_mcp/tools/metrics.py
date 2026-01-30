"""Metrics tools for querying and submitting Datadog metrics."""

from datadog_api_client.v1.api.metrics_api import MetricsApi
from datadog_api_client.v2.api.metrics_api import MetricsApi as MetricsApiV2
from datadog_api_client.v2.model.metric_intake_type import MetricIntakeType
from datadog_api_client.v2.model.metric_payload import MetricPayload
from datadog_api_client.v2.model.metric_point import MetricPoint
from datadog_api_client.v2.model.metric_series import MetricSeries

from ..auth import DatadogAuth
from ..utils.auth import get_api_instance
from ..utils.response import ResponseBuilder, format_error_response


def query_metrics(
    query: str, from_time: int, to_time: int, auth: DatadogAuth | None = None
) -> dict:
    """Query Datadog metrics with a query expression.

    Args:
        query: Metric query using Datadog syntax (e.g., "avg:system.cpu.user{*}")
        from_time: Start time as Unix timestamp (seconds)
        to_time: End time as Unix timestamp (seconds)
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: Query results containing series data (auto-truncated if too large)
    """
    api_instance, auth = get_api_instance(MetricsApi, auth)

    try:
        response = api_instance.query_metrics(_from=from_time, to=to_time, query=query)

        # Format response
        series_data = []
        if hasattr(response, "series") and response.series:
            for series in response.series:
                # Convert series to dict if it's an object
                if hasattr(series, "to_dict"):
                    series_dict = series.to_dict()
                else:
                    series_dict = series if isinstance(series, dict) else {}

                series_entry = {
                    "metric": series_dict.get("metric"),
                    "display_name": series_dict.get("display_name"),
                    "unit": str(series_dict.get("unit")) if series_dict.get("unit") else None,
                    "pointlist": series_dict.get("pointlist", []),
                    "scope": series_dict.get("scope"),
                    "interval": series_dict.get("interval"),
                    "aggr": series_dict.get("aggr"),
                    "expression": series_dict.get("expression"),
                }
                series_data.append(series_entry)

        # Use ResponseBuilder for automatic size limiting
        return ResponseBuilder.success(
            "series",
            series_data,
            from_date=response.from_date if hasattr(response, "from_date") else from_time,
            to_date=response.to_date if hasattr(response, "to_date") else to_time,
            query=query,
            res_type=response.res_type if hasattr(response, "res_type") else None,
            resp_version=response.resp_version if hasattr(response, "resp_version") else None,
        )

    except Exception as e:
        return format_error_response("series", e)


def list_metrics(
    filter: str | None = None, limit: int = 50, auth: DatadogAuth | None = None
) -> dict:
    """List available metrics in Datadog.

    Args:
        filter: Optional filter string to search metrics by name (e.g., "system.cpu")
        limit: Maximum number of metrics to return (default: 50, max: 50)
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: List of metric names (size-limited)
    """
    api_instance, auth = get_api_instance(MetricsApi, auth)

    try:
        if filter:
            response = api_instance.list_metrics(q=filter)
        else:
            response = api_instance.list_metrics(q="*")

        metrics = []
        if hasattr(response, "metrics") and response.metrics:
            metrics = response.metrics[:limit]

        return ResponseBuilder.success("metrics", metrics)

    except Exception as e:
        return format_error_response("metrics", e)


def submit_metrics(
    metric_name: str,
    points: list[tuple[int, float]],
    metric_type: str = "gauge",
    tags: list[str] | None = None,
    host: str | None = None,
    interval: int | None = None,
    auth: DatadogAuth | None = None,
) -> dict:
    """Submit custom metrics to Datadog.

    Args:
        metric_name: Name of the metric (e.g., "custom.metric.name")
        points: List of [timestamp, value] tuples where timestamp is Unix time in seconds
        metric_type: Type of metric - "gauge", "count", "rate" (default: "gauge")
        tags: Optional list of tags (e.g., ["env:prod", "service:api"])
        host: Optional host name
        interval: Optional interval in seconds for rate/count metrics
        auth: DatadogAuth instance (injected dependency)

    Returns:
        dict: Submission result
    """
    if auth is None:
        auth = DatadogAuth()

    # Map string type to enum
    type_mapping = {
        "gauge": MetricIntakeType(0),
        "count": MetricIntakeType(1),
        "rate": MetricIntakeType(2),
    }

    if metric_type not in type_mapping:
        return {
            "success": False,
            "error": f"Invalid metric_type. Must be one of: {list(type_mapping.keys())}",
        }

    # Use API client directly - no context manager needed
    api_instance = MetricsApiV2(auth.api_client)

    try:
        # Build metric points
        metric_points = [MetricPoint(timestamp=int(ts), value=float(val)) for ts, val in points]

        # Build metric series
        series_kwargs = {
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

        # Submit metrics
        body = MetricPayload(series=[series])
        response = api_instance.submit_metrics(body=body)

        return {
            "success": True,
            "metric_name": metric_name,
            "points_submitted": len(points),
            "response": response.to_dict() if hasattr(response, "to_dict") else str(response),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
