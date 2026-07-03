"""Logs tools for searching and retrieving Datadog logs."""

from __future__ import annotations

from typing import Any

from datadog_api_client.v2.api.logs_api import LogsApi
from datadog_api_client.v2.model.logs_list_request import LogsListRequest
from datadog_api_client.v2.model.logs_list_request_page import LogsListRequestPage
from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
from datadog_api_client.v2.model.logs_sort import LogsSort
from fastmcp import FastMCP
from pydantic import Field, model_validator

from ..auth import DatadogAuth, get_auth_instance
from ..utils.annotations import READ_ONLY
from ..utils.auth import get_api_instance
from ..utils.pagination import DEFAULT_PAGE_SIZE, clamp_page_size
from ..utils.response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    finalize_list_response,
    format_error_response,
)


class LogEntry(DatadogModel):
    """A single log entry, flattened from Datadog's `{id, type, attributes}` envelope."""

    id: str | None = None
    timestamp: str | None = None
    message: str | None = None
    status: str | None = None
    service: str | None = None
    host: str | None = None
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _flatten_datadog_envelope(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("attributes"), dict):
            return {"id": data.get("id"), **data["attributes"]}
        return data


class SearchLogsResponse(PaginatedListResponse):
    """Response for `search_logs`."""

    logs: list[LogEntry] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class GetLogDetailsResponse(ToolResponse):
    """Response for `get_log_details`."""

    log: LogEntry | None = None


def _search_logs(
    query: str,
    from_time: str,
    to_time: str,
    page_size: int,
    cursor: str | None,
    sort: str,
    indexes: list[str] | None,
    auth: DatadogAuth,
) -> SearchLogsResponse:
    page_size = clamp_page_size(page_size)
    api_instance = get_api_instance(LogsApi, auth)

    page_config = LogsListRequestPage(limit=page_size)
    if cursor:
        page_config.cursor = cursor

    body = LogsListRequest(
        filter=LogsQueryFilter(
            query=query,
            **{"from": from_time, "to": to_time},  # type: ignore[arg-type]
            indexes=indexes or ["*"],
        ),
        page=page_config,
        sort=LogsSort(sort),  # type: ignore[no-untyped-call]
    )

    try:
        response = api_instance.list_logs(body=body)

        logs = [LogEntry.model_validate(log.to_dict()) for log in (response.data or [])]

        next_cursor: str | None = None
        has_more = False
        page = getattr(response.meta, "page", None) if response.meta else None
        if page is not None and getattr(page, "after", None):
            next_cursor = page.after
            has_more = True

        result = SearchLogsResponse(logs=logs, next_cursor=next_cursor, has_more=has_more)
        return finalize_list_response(result, "logs")

    except Exception as e:  # noqa: BLE001 - classified and surfaced via format_error_response
        return format_error_response(SearchLogsResponse, e, required_scope="logs_read")


def _get_log_details(log_id: str, auth: DatadogAuth) -> GetLogDetailsResponse:
    api_instance = get_api_instance(LogsApi, auth)

    try:
        response = api_instance.get_log(log_id)  # type: ignore[attr-defined]
        if response is None or response.data is None:
            return GetLogDetailsResponse(success=False, error=f"Log not found: {log_id}")

        return GetLogDetailsResponse(log=LogEntry.model_validate(response.data.to_dict()))

    except Exception as e:  # noqa: BLE001
        return format_error_response(GetLogDetailsResponse, e, required_scope="logs_read")


def register_logs_tools(mcp: FastMCP) -> None:
    """Register `search_logs` and `get_log_details` on `mcp`."""

    @mcp.tool(annotations=READ_ONLY)
    def search_logs(
        query: str,
        from_time: str,
        to_time: str,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
        sort: str = "timestamp",
        indexes: list[str] | None = None,
    ) -> SearchLogsResponse:
        """Search and VIEW log entries. Returns paginated results.

        IMPORTANT: Use this ONLY when you need to VIEW log content for debugging.
        For COUNTING logs or unique values, use count_logs or count_unique_values
        instead - they are much faster and lighter since they never fetch raw
        log content.

        Use this when:
        - Need to view actual log messages and details
        - Debugging specific issues
        - Investigating error details

        DO NOT use for:
        - Counting logs (use count_logs)
        - Counting unique sessions/users (use count_unique_values)
        - Statistical analysis (use aggregate_logs_by_field)

        Examples:
            search_logs("status:error", "now-1h", "now")
            search_logs("service:api", "2024-01-28T10:00:00Z", "2024-01-28T11:00:00Z", page_size=50)

        Args:
            query: Search query using Datadog log search syntax (e.g. "status:error service:api")
            from_time: Start time - ISO 8601 (e.g. "2024-01-28T10:00:00Z"), relative date
                math (e.g. "now-1h", "now"), or a millisecond timestamp
            to_time: End time - same accepted formats as from_time
            page_size: Logs per page (default: 25, max: 50)
            cursor: Pagination cursor from a previous response's next_cursor field
            sort: Sort order, "timestamp" or "-timestamp" for descending
            indexes: Optional list of index names to search (e.g. ["main", "retention"])
        """
        return _search_logs(
            query, from_time, to_time, page_size, cursor, sort, indexes, get_auth_instance()
        )

    @mcp.tool(annotations=READ_ONLY)
    def get_log_details(log_id: str) -> GetLogDetailsResponse:
        """Get complete details of a specific log entry.

        Use this when: need full information about a particular log (after searching).

        Args:
            log_id: Unique log identifier, as returned in a search_logs result's "id" field
        """
        return _get_log_details(log_id, get_auth_instance())
