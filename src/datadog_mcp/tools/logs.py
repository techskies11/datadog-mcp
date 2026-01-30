"""Logs tools for searching and retrieving Datadog logs."""

from datetime import datetime
from typing import Optional
from datadog_api_client.v2.api.logs_api import LogsApi
from datadog_api_client.v2.model.logs_list_request import LogsListRequest
from datadog_api_client.v2.model.logs_list_request_page import LogsListRequestPage
from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
from datadog_api_client.v2.model.logs_sort import LogsSort

from ..auth import DatadogAuth
from ..utils.response import ResponseBuilder, format_error_response
from ..utils.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..utils.auth import get_api_instance


def search_logs(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int = DEFAULT_PAGE_SIZE,
    cursor: Optional[str] = None,
    sort: str = "timestamp",
    indexes: Optional[list[str]] = None,
    auth: Optional[DatadogAuth] = None
) -> dict:
    """Search Datadog logs with query syntax (paginated).
    
    Args:
        query: Search query using Datadog log search syntax (e.g., "status:error service:api")
        from_time: Start time (ISO 8601, date math like "now-1h", or timestamp ms)
        to_time: End time (ISO 8601, date math like "now", or timestamp ms)
        page_size: Number of logs per page (default: 25, max: 50)
        cursor: Pagination cursor from previous response's next_cursor field
        sort: Sort order, either "timestamp" or "-timestamp" for descending (default: "timestamp")
        indexes: Optional list of index names to search (e.g., ["main", "retention"])
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Paginated search results with logs, next_cursor, and has_more flag
        
    Note: For counting logs without fetching all data, use count_logs or count_unique instead.
    """
    # Validate and cap page_size
    page_size = min(page_size, MAX_PAGE_SIZE)
    
    api_instance, auth = get_api_instance(LogsApi, auth)
    
    # Build the request with pagination
    page_config = LogsListRequestPage(limit=page_size)
    if cursor:
        page_config.cursor = cursor
    
    body = LogsListRequest(
        filter=LogsQueryFilter(
            query=query,
            **{"from": from_time, "to": to_time},  # Usar kwargs para evitar conflicto con keyword
            indexes=indexes or ["*"]
        ),
        page=page_config,
        sort=LogsSort(sort)
    )
    
    try:
        response = api_instance.list_logs(body=body)
        
        # Format response
        logs = []
        if hasattr(response, 'data') and response.data:
            for log in response.data:
                log_entry = {
                    "id": log.id if hasattr(log, 'id') else None,
                    "timestamp": log.attributes.timestamp.isoformat() if hasattr(log.attributes, 'timestamp') else None,
                    "message": log.attributes.message if hasattr(log.attributes, 'message') else None,
                    "status": log.attributes.status if hasattr(log.attributes, 'status') else None,
                    "service": log.attributes.service if hasattr(log.attributes, 'service') else None,
                    "tags": log.attributes.tags if hasattr(log.attributes, 'tags') else [],
                    "attributes": log.attributes.attributes if hasattr(log.attributes, 'attributes') else {}
                }
                logs.append(log_entry)
        
        # Extract pagination info
        next_cursor = None
        has_more = False
        if hasattr(response, 'meta') and hasattr(response.meta, 'page'):
            if hasattr(response.meta.page, 'after'):
                next_cursor = response.meta.page.after
                has_more = True
        
        # Use ResponseBuilder for automatic size limiting
        return ResponseBuilder.success(
            "logs",
            logs,
            has_more=has_more,
            next_cursor=next_cursor,
            page_size=page_size
        )
        
    except Exception as e:
        return format_error_response("logs", e)


def get_log_details(log_id: str, auth: Optional[DatadogAuth] = None) -> dict:
    """Get detailed information about a specific log entry.
    
    Args:
        log_id: The unique identifier of the log entry
        auth: DatadogAuth instance (injected dependency)
    
    Returns:
        dict: Detailed log information
    """
    api_instance, auth = get_api_instance(LogsApi, auth)
    
    try:
        response = api_instance.get_log(log_id)
        
        if not response or not hasattr(response, 'data'):
            return {
                "success": False,
                "error": "Log not found"
            }
        
        log = response.data
        
        return {
            "success": True,
            "log": {
                "id": log.id if hasattr(log, 'id') else None,
                "timestamp": log.attributes.timestamp.isoformat() if hasattr(log.attributes, 'timestamp') else None,
                "message": log.attributes.message if hasattr(log.attributes, 'message') else None,
                "status": log.attributes.status if hasattr(log.attributes, 'status') else None,
                "service": log.attributes.service if hasattr(log.attributes, 'service') else None,
                "tags": log.attributes.tags if hasattr(log.attributes, 'tags') else [],
                "host": log.attributes.host if hasattr(log.attributes, 'host') else None,
                "attributes": log.attributes.attributes if hasattr(log.attributes, 'attributes') else {},
                "raw": log.attributes.to_dict() if hasattr(log, 'attributes') else {}
            }
        }
        
    except Exception as e:
        return format_error_response("log", e)
