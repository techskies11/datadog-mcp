"""Pydantic response infrastructure shared by every tool domain.

Two model families live here, matching the inbound/outbound split documented
in `.cursor/rules/pydantic-models.mdc`:

- `DatadogModel`: for data parsed *from* Datadog API responses. Tolerant
  (`extra="ignore"`) because Datadog can add fields to its API responses at
  any time without notice; strict validation on inbound data would turn
  every Datadog-side addition into an outage for this server.
- `ToolResponse` / `PaginatedListResponse`: for data returned *by* tools to
  the MCP client. Strict (`extra="forbid"`) because this is data we fully
  control - if a field appears here it must be declared, never injected
  ad-hoc at runtime.

Tool responses never use `SuccessModel | ErrorModel` unions: FastMCP wraps
union returns as `structuredContent = {"result": ...}` instead of the flat
shape a single model produces, which would silently change the wire format
for every tool. Every response model instead carries its own `success` and
`error` fields.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

# NOTE ON THE SIZE BUDGET: FastMCP sends a tool result twice on the wire -
# once as human-readable text content, once as machine-readable
# structuredContent - so the bytes actually transmitted are roughly double
# what we measure here. This budget is measured against a single serialized
# copy of the response and is kept conservative for that reason.
MAX_RESPONSE_SIZE_BYTES = 50_000


class _ExcludeNoneModel(BaseModel):
    """Mixin that excludes `None`-valued fields from every serialization path.

    FastMCP builds a tool's `structuredContent` via `pydantic_core.to_jsonable_python`,
    which defaults to `exclude_none=False` - a plain `model_dump(exclude_none=True)`
    at the call site would not affect that path. Overriding serialization at the
    model level instead makes `exclude_none` the model's actual behavior everywhere
    (`model_dump`, `model_dump_json`, and `to_jsonable_python` alike), which is what
    keeps optional/absent fields (like `next_cursor` on a non-paginated response)
    out of the wire shape instead of appearing as `null`.
    """

    @model_serializer(mode="wrap")
    def _exclude_none_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class DatadogModel(_ExcludeNoneModel):
    """Base for models parsed from Datadog API responses (inbound, tolerant)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ToolResponse(_ExcludeNoneModel):
    """Base for every tool's return type (outbound, strict).

    `success`/`error` live on every response so tools never need a
    `Model | ErrorModel` union return type.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    error: str | None = None


ResponseT = TypeVar("ResponseT", bound="PaginatedListResponse")
ToolResponseT = TypeVar("ToolResponseT", bound="ToolResponse")


class PaginatedListResponse(ToolResponse):
    """Base for tool responses whose payload is a single named list of items.

    Subclasses add their own typed list field (e.g. `logs: list[LogEntry]`)
    plus any domain-specific metadata, and pass the list field's *name* to
    `finalize_list_response` explicitly so truncation always targets the
    right field even as new response models are added.
    """

    count: int = 0
    truncated: bool = False
    warning: str | None = None
    total_available: int | None = None


def finalize_list_response(response: ResponseT, list_field: str) -> ResponseT:
    """Set `count` and truncate `list_field` if the response is too large.

    Uses binary search (as the original implementation did) to find the
    maximum number of items that fit within `MAX_RESPONSE_SIZE_BYTES`.
    """
    items = list(getattr(response, list_field))
    response = response.model_copy(update={"count": len(items)})

    size = len(response.model_dump_json())
    if size <= MAX_RESPONSE_SIZE_BYTES or len(items) <= 1:
        return response

    original_count = len(items)
    low, high, best = 1, original_count, 1
    while low <= high:
        mid = (low + high) // 2
        candidate = response.model_copy(update={list_field: items[:mid]})
        candidate_size = len(candidate.model_dump_json())
        if candidate_size <= MAX_RESPONSE_SIZE_BYTES:
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    return response.model_copy(
        update={
            list_field: items[:best],
            "count": best,
            "truncated": True,
            "total_available": original_count,
            "warning": (
                f"Response truncated from {original_count} to {best} items to stay "
                f"within the {MAX_RESPONSE_SIZE_BYTES}-byte response budget. Use "
                "pagination (cursor) or a narrower query/filter to see the rest."
            ),
        }
    )


def classify_api_exception(error: Exception, required_scope: str | None = None) -> str:
    """Turn an `ApiException` into an actionable message instead of a raw stringification.

    A 403 with a generic message leads an agent to retry blindly; naming the
    likely missing scope lets it explain the problem to the user instead.
    """
    status = getattr(error, "status", None)
    if status == 403:
        scope_hint = (
            f" (this operation likely requires the '{required_scope}' scope)"
            if required_scope
            else ""
        )
        return (
            "Datadog rejected this request: the configured app key is missing a "
            f"required permission{scope_hint}. This is not something the agent can "
            f"retry around - a Datadog admin needs to grant the scope. Raw error: {error}"
        )
    if status == 429:
        return (
            "Datadog rate-limited this request (HTTP 429). The client already "
            f"retries transient rate limits automatically; if this error surfaced "
            f"anyway, the retry budget was exhausted - wait before trying again. "
            f"Raw error: {error}"
        )
    return str(error)


def format_error_response(
    response_cls: type[ToolResponseT],
    error: Exception,
    *,
    required_scope: str | None = None,
) -> ToolResponseT:
    """Build a `success=False` response of the right type, with a classified error message."""
    return response_cls(success=False, error=classify_api_exception(error, required_scope))
