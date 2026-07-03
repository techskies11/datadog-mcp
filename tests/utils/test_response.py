"""Unit tests for the shared Pydantic response infrastructure."""

from __future__ import annotations

from datadog_api_client.exceptions import ApiException

from datadog_mcp.utils.response import (
    PaginatedListResponse,
    classify_api_exception,
    finalize_list_response,
    format_error_response,
)


class _ItemsResponse(PaginatedListResponse):
    items: list[str] = []


def test_finalize_list_response_sets_count_without_truncating_small_lists() -> None:
    response = _ItemsResponse(items=["a", "b", "c"])

    result = finalize_list_response(response, "items")

    assert result.count == 3
    assert result.truncated is False
    assert result.warning is None
    assert result.total_available is None
    assert result.items == ["a", "b", "c"]


def test_finalize_list_response_truncates_oversized_lists() -> None:
    big_items = [f"item-{i}-{'x' * 500}" for i in range(500)]
    response = _ItemsResponse(items=big_items)

    result = finalize_list_response(response, "items")

    assert result.truncated is True
    assert result.total_available == 500
    assert result.count == len(result.items)
    assert result.count < 500
    assert result.warning is not None

    # The truncated response itself must still respect the byte budget.
    from datadog_mcp.utils.response import MAX_RESPONSE_SIZE_BYTES

    assert len(result.model_dump_json(exclude_none=True)) <= MAX_RESPONSE_SIZE_BYTES


def test_finalize_list_response_excludes_none_fields_from_json() -> None:
    response = _ItemsResponse(items=["a"])
    result = finalize_list_response(response, "items")

    dumped = result.model_dump_json(exclude_none=True)
    assert "warning" not in dumped
    assert "total_available" not in dumped
    assert "error" not in dumped


def test_classify_api_exception_names_missing_scope_on_403() -> None:
    error = ApiException(status=403, reason="Forbidden")

    message = classify_api_exception(error, required_scope="metrics_metadata_write")

    assert "metrics_metadata_write" in message
    assert "admin" in message.lower()


def test_classify_api_exception_flags_rate_limit_on_429() -> None:
    error = ApiException(status=429, reason="Too Many Requests")

    message = classify_api_exception(error)

    assert "rate-limited" in message.lower()


def test_classify_api_exception_passes_through_other_errors() -> None:
    error = ValueError("boom")

    message = classify_api_exception(error)

    assert message == "boom"


def test_format_error_response_builds_failed_response_of_correct_type() -> None:
    error = ApiException(status=403, reason="Forbidden")

    result = format_error_response(_ItemsResponse, error, required_scope="logs_read_config")

    assert isinstance(result, _ItemsResponse)
    assert result.success is False
    assert result.error is not None
    assert "logs_read_config" in result.error
    assert result.items == []
