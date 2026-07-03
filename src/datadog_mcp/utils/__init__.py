"""Shared utilities for Datadog MCP tools."""

from .auth import get_api_instance
from .pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .response import (
    DatadogModel,
    PaginatedListResponse,
    ToolResponse,
    classify_api_exception,
    finalize_list_response,
    format_error_response,
)

__all__ = [
    "DatadogModel",
    "ToolResponse",
    "PaginatedListResponse",
    "finalize_list_response",
    "classify_api_exception",
    "format_error_response",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "get_api_instance",
]
