"""APM tools for searching traces and spans in Datadog."""

from typing import Optional
from datadog_api_client.v2.api.apm_api import APMApi
from datadog_api_client.v2.api.spans_api import SpansApi
from datadog_api_client.v1.api.service_level_objectives_api import ServiceLevelObjectivesApi
from datadog_api_client.v2.model.spans_list_request import SpansListRequest
from datadog_api_client.v2.model.spans_list_request_data import SpansListRequestData
from datadog_api_client.v2.model.spans_list_request_attributes import SpansListRequestAttributes
from datadog_api_client.v2.model.spans_query_filter import SpansQueryFilter
from datadog_api_client.v2.model.spans_list_request_page import SpansListRequestPage
from datadog_api_client.v2.model.spans_sort import SpansSort
from datadog_api_client.v2.model.spans_list_request_type import SpansListRequestType

from ..auth import DatadogAuth
from ..utils.response import ResponseBuilder, format_error_response
from ..utils.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..utils.auth import get_api_instance


def search_spans(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    cursor: Optional[str] = None,
    sort: str = "timestamp",
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Search APM spans with query syntax (paginated).
    
    Args:
        query: Search query using Datadog span search syntax (e.g., "service:web-store @http.status_code:500")
        from_time: Start time (ISO 8601, date math like "now-1h", or timestamp ms)
        to_time: End time (ISO 8601, date math like "now", or timestamp ms)
        page_size: Number of spans per page (default: 25, max: 50)
        cursor: Pagination cursor from previous response's next_cursor field
        sort: Sort order, either "timestamp" or "-timestamp" for descending (default: "timestamp")
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Paginated search results with spans, next_cursor, and has_more flag
    """
    # Validate and cap page_size
    page_size = min(page_size, MAX_PAGE_SIZE)
    
    api_instance, auth = get_api_instance(SpansApi, auth)
    
    try:
        # Build the request body with proper structure
        page_config = SpansListRequestPage(limit=page_size)
        if cursor:
            page_config.cursor = cursor
        
        body = SpansListRequest(
            data=SpansListRequestData(
                attributes=SpansListRequestAttributes(
                    filter=SpansQueryFilter(
                        query=query,
                        **{"from": from_time, "to": to_time}  # Use kwargs for 'from' and 'to'
                    ),
                    page=page_config,
                    sort=SpansSort(sort)
                ),
                type=SpansListRequestType("search_request")
            )
        )
        
        response = api_instance.list_spans(body=body)
        
        # Format response
        spans = []
        if hasattr(response, 'data') and response.data:
            for span in response.data:
                span_entry = {
                    "span_id": span.id if hasattr(span, 'id') else None,
                    "type": str(span.type) if hasattr(span, 'type') else None,
                }
                
                if hasattr(span, 'attributes'):
                    attrs = span.attributes
                    span_entry.update({
                        "service": attrs.service if hasattr(attrs, 'service') else None,
                        "resource": attrs.resource_name if hasattr(attrs, 'resource_name') else None,
                        "operation": attrs.operation_name if hasattr(attrs, 'operation_name') else None,
                        "start": attrs.start.isoformat() if hasattr(attrs, 'start') else None,
                        "duration": attrs.duration if hasattr(attrs, 'duration') else None,
                        "tags": attrs.tags if hasattr(attrs, 'tags') else {},
                        "trace_id": attrs.trace_id if hasattr(attrs, 'trace_id') else None,
                        "parent_id": attrs.parent_id if hasattr(attrs, 'parent_id') else None
                    })
                
                spans.append(span_entry)
        
        # Extract pagination info
        next_cursor = None
        has_more = False
        if hasattr(response, 'meta') and hasattr(response.meta, 'page'):
            if hasattr(response.meta.page, 'after'):
                next_cursor = response.meta.page.after
                has_more = True
        
        # Use ResponseBuilder for automatic size limiting
        return ResponseBuilder.success(
            "spans",
            spans,
            has_more=has_more,
            next_cursor=next_cursor,
            page_size=page_size
        )
        
    except Exception as e:
        return format_error_response("spans", e)


def get_trace(trace_id: str, auth: Optional[DatadogAuth] = None) -> dict:
    """Get complete trace information by trace ID.
    
    Args:
        trace_id: The unique identifier of the trace
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Complete trace with all spans (auto-truncated if too large)
    """
    from datadog_api_client.v2.api.traces_api import TracesApi
    api_instance, auth = get_api_instance(TracesApi, auth)
    
    try:
        # Note: The Datadog API doesn't have a direct "get trace by ID" endpoint
        # We need to search for spans with the trace_id
        response = api_instance.list_traces(
            filter_query=f"trace_id:{trace_id}",
            page_limit=1000
        )
        
        spans = []
        if hasattr(response, 'data') and response.data:
            for span in response.data:
                span_entry = {
                    "span_id": span.id if hasattr(span, 'id') else None,
                    "type": str(span.type) if hasattr(span, 'type') else None,
                }
                
                if hasattr(span, 'attributes'):
                    attrs = span.attributes
                    span_entry.update({
                        "service": attrs.service if hasattr(attrs, 'service') else None,
                        "resource": attrs.resource_name if hasattr(attrs, 'resource_name') else None,
                        "operation": attrs.operation_name if hasattr(attrs, 'operation_name') else None,
                        "start": attrs.start.isoformat() if hasattr(attrs, 'start') else None,
                        "duration": attrs.duration if hasattr(attrs, 'duration') else None,
                        "tags": attrs.tags if hasattr(attrs, 'tags') else {},
                        "trace_id": attrs.trace_id if hasattr(attrs, 'trace_id') else None,
                        "parent_id": attrs.parent_id if hasattr(attrs, 'parent_id') else None,
                        "error": attrs.error if hasattr(attrs, 'error') else 0
                    })
                
                spans.append(span_entry)
        
        if not spans:
            return {
                "success": False,
                "error": f"No trace found with ID: {trace_id}"
            }
        
        # Calculate trace duration and find root span
        root_span = None
        total_duration = 0
        for span in spans:
            if not span.get("parent_id"):
                root_span = span
            if span.get("duration"):
                total_duration = max(total_duration, span["duration"])
        
        # Use ResponseBuilder for automatic size limiting
        return ResponseBuilder.success(
            "spans",
            spans,
            trace_id=trace_id,
            root_span=root_span,
            duration=total_duration
        )
        
    except Exception as e:
        return format_error_response("spans", e)


def list_services(
    env: Optional[str] = None,
    limit: int = 50,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """List available APM services.
    
    Args:
        env: Optional environment filter (e.g., "prod", "staging")
        limit: Maximum number of services to return (default: 50, max: 50)
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: List of service names (size-limited)
    """
    api_instance, auth = get_api_instance(SpansApi, auth)
    
    try:
        # Note: Datadog doesn't have a direct "list services" endpoint in v2
        # We'll search for spans grouped by service
        
        # Build query with environment filter if provided
        query = f"env:{env}" if env else "*"
        
        # Get spans and extract unique services
        response = api_instance.aggregate_spans(
            body={
                "filter": {
                    "query": query,
                    "from": "now-1h",
                    "to": "now"
                },
                "compute": [{"aggregation": "count"}],
                "group_by": [{"facet": "service"}]
            }
        )
        
        services = []
        if hasattr(response, 'data') and response.data:
            for bucket in response.data[:limit]:
                if hasattr(bucket, 'by') and 'service' in bucket.by:
                    services.append(bucket.by['service'])
        
        return ResponseBuilder.success(
            "services",
            services,
            environment=env
        )
        
    except Exception as e:
        # Fallback: return a helpful error message
        return {
            "success": False,
            "error": str(e),
            "message": "Try using search_spans with a broad query to discover services",
            "services": []
        }
