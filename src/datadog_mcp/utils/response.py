"""Response formatting utilities with automatic size limits."""

import json
from typing import Any

# Configuration constants
MAX_RESPONSE_SIZE_BYTES = 50_000  # 50KB max response size
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 50


class ResponseBuilder:
    """Builder for consistent API responses with automatic size limiting."""

    @staticmethod
    def success(data_key: str, data: list[Any], **metadata: Any) -> dict[str, Any]:
        """Create a success response with automatic size checking.

        Args:
            data_key: Key name for the data array (e.g., "logs", "spans", "dashboards")
            data: List of data items to return
            **metadata: Additional metadata fields (page, has_next, etc.)

        Returns:
            dict: Formatted response with truncation if needed
        """
        response = {"success": True, data_key: data, "count": len(data), **metadata}
        return ResponseBuilder._check_and_truncate(response, data_key)

    @staticmethod
    def _check_and_truncate(response: dict[str, Any], data_key: str) -> dict[str, Any]:
        """Check response size and truncate if necessary.

        Args:
            response: Response dictionary
            data_key: Key containing the data array

        Returns:
            dict: Possibly truncated response with warning
        """
        try:
            size = len(json.dumps(response, default=str))

            if size > MAX_RESPONSE_SIZE_BYTES:
                data = response[data_key]
                original_count = len(data)

                # Binary search for maximum items that fit
                low, high = 1, original_count
                best_count = 1

                while low <= high:
                    mid = (low + high) // 2
                    test_response = {**response, data_key: data[:mid]}
                    test_size = len(json.dumps(test_response, default=str))

                    if test_size <= MAX_RESPONSE_SIZE_BYTES:
                        best_count = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                # Apply truncation
                response[data_key] = data[:best_count]
                response["count"] = best_count
                response["truncated"] = True
                response["warning"] = (
                    f"Response truncated from {original_count} to {best_count} items "
                    f"to stay within {MAX_RESPONSE_SIZE_BYTES} bytes limit. "
                    f"Use pagination or aggregation tools for complete data."
                )
                response["total_available"] = original_count

        except Exception as e:
            # If size check fails, add warning but don't fail the response
            response["size_check_error"] = str(e)

        return response


def format_error_response(data_key: str, error: Exception) -> dict[str, Any]:
    """Format a consistent error response.

    Args:
        data_key: Key name for the empty data array
        error: Exception that occurred

    Returns:
        dict: Formatted error response
    """
    return {"success": False, "error": str(error), data_key: []}
