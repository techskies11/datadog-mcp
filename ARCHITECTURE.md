# Architecture Overview

## System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                          Cursor IDE                              │
│  User: "What monitors are alerting in prod right now?"           │
│                              ↓                                   │
│                        AI Agent                                  │
│  Decides to use: list_all_monitors(group_states="alert", ...)    │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                   MCP Protocol over stdio (FastMCP)
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                 Datadog MCP Server (Python)                      │
│                                                                   │
│  server.py — composition only                                    │
│    • FastMCP("Datadog Integration") instance                     │
│    • register_<domain>_tools(mcp) for each domain module          │
│    • @mcp.resource / @mcp.prompt definitions                     │
│                              ↓                                   │
│  auth.py — DatadogAuth singleton                                 │
│    • get_auth_instance() reads DD_API_KEY / DD_APP_KEY / DD_SITE │
│    • builds one datadog_api_client.Configuration + ApiClient     │
│                              ↓                                   │
│  tools/<domain>.py — one module per Datadog domain                │
│    logs.py          search_logs, get_log_details                 │
│    aggregations.py  count_logs, count_unique_values,              │
│                      aggregate_logs_by_field                      │
│    metrics.py        query_metrics, list_available_metrics,       │
│                      list_active_metrics, describe_metric,        │
│                      send_custom_metric                           │
│    dashboards.py    list/get/create/update dashboard, widget      │
│                      pre-validation, datadog://widget-templates   │
│    apm.py            search_apm_traces, get_full_trace,           │
│                      list_apm_services, aggregate_spans           │
│    monitors.py      list/search/get/create/update/validate        │
│                      monitor, silence/unsilence                   │
│    downtimes.py     list/get/schedule/update downtime             │
│                                                                   │
│  utils/response.py — Pydantic response infrastructure shared by   │
│                      every domain (see "Response model layering")│
│  utils/annotations.py — shared ToolAnnotations presets            │
│  utils/time.py        — parse_time_value() shared by logs/spans/  │
│                          downtimes for flexible time inputs        │
└─────────────────────────────────────────────────────────────────┘
                               ↓
                      datadog-api-client (Python)
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                          Datadog APIs                             │
│   Logs v2 · Metrics v1/v2 · Dashboards v1 · APM v2 (Spans +       │
│   APMTrace) · Monitors v1 · Downtimes v2                          │
│              https://api.<DD_SITE> (region-specific)              │
└─────────────────────────────────────────────────────────────────┘
```

## Component details

### Server layer (`server.py`)
- **Framework**: FastMCP (not the raw MCP Python SDK) - tools/resources/prompts are plain decorated functions; schemas are generated from Pydantic models and type hints automatically.
- **Transport**: stdio, launched by Cursor via `fastmcp run src/datadog_mcp/server.py`.
- **Registration**: each domain module exposes `register_<domain>_tools(mcp)`; `server.py` calls all of them plus defines resources/prompts directly. It contains no tool business logic itself (~210 lines total).

### Authentication layer (`auth.py`)
- `DatadogAuth` reads `DD_API_KEY`, `DD_APP_KEY`, `DD_SITE` (default `datadoghq.com`) and builds one `datadog_api_client.Configuration`/`ApiClient` pair, with `enable_retry=True` (handles `429`s and honors `X-Ratelimit-Reset`) and an explicit `request_timeout`.
- `get_auth_instance()` is a module-level singleton factory living in `auth.py` itself (not `server.py`), which avoids a `server → tools → server` import cycle.
- `utils/auth.py`'s `get_api_instance(api_class, auth)` is a small generic factory (`TypeVar`-based) that constructs a Datadog API client class bound to the shared `ApiClient`. Auth is always passed explicitly - no implicit "or create one" default - so tests can inject a fake/mocked `DatadogAuth` without patching globals.

### Tools layer (`tools/*.py`)
Each domain module follows the same three-part shape:
1. **Pydantic models** - inbound models parsed from Datadog responses (`DatadogModel`, tolerant) and outbound response models returned to the MCP client (`ToolResponse`/`PaginatedListResponse`, strict). See "Response model layering" below.
2. **`_function(...)` implementations** - plain functions taking an explicit `auth: DatadogAuth` parameter (dependency injection), doing the actual API call + Pydantic parsing + error classification. These are what unit tests call directly, with a mocked Datadog API class and `fake_auth` fixture - no MCP machinery involved.
3. **`register_<domain>_tools(mcp)`** - defines the `@mcp.tool(annotations=...)`-decorated public functions, which just resolve `get_auth_instance()` and delegate to the `_function`. Docstrings live here once (see Documentation Standards rule) and are the single source FastMCP uses to build each tool's description/parameter schema.

### Response model layering (`utils/response.py`)
- `DatadogModel` (inbound): `extra="ignore"`, tolerant - Datadog can add response fields at any time without warning; strict validation here would turn every Datadog-side addition into an outage.
- `ToolResponse` / `PaginatedListResponse` (outbound): `extra="forbid"`, strict - this is data this server fully controls, so every field must be declared. Every response carries `success: bool` and `error: str | None` directly (no `Success | Error` union return types - FastMCP serializes a union return as `structuredContent = {"result": ...}`, which would silently change every tool's wire shape).
- Both share an `_ExcludeNoneModel` mixin implementing `exclude_none` at the serializer level (via `model_serializer(mode="wrap")`), because FastMCP's `structuredContent` path (`pydantic_core.to_jsonable_python`) doesn't otherwise honor `model_dump(exclude_none=True)` called at the call site.
- `PaginatedListResponse` declares `count`/`truncated`/`warning`/`total_available` up front; `finalize_list_response(response, list_field)` binary-searches the largest prefix of `list_field` that fits `MAX_RESPONSE_SIZE_BYTES` (50 KB - conservative, since FastMCP transmits both a text and a structured copy of every result).
- `classify_api_exception` turns a raw `ApiException` into an actionable message: 403 → names the likely missing scope (so the agent explains the problem instead of retrying blindly), 429 → notes the client already retries transient rate limits automatically.

### Tool safety (`utils/annotations.py`)
Four honest `ToolAnnotations` presets (`READ_ONLY`, `WRITE_ADDITIVE`, `WRITE_OVERWRITE`, `STATE_TOGGLE`) are shared across domains so equivalent operations (e.g. every domain's "update" tool) get consistent hints. See the table in [README.md](README.md#tool-safety-annotations).

## Data flow example: `search_logs`

1. **Agent decision** - Cursor's agent picks `search_logs(query="status:error service:api", from_time="now-1h", to_time="now")`.
2. **MCP dispatch** - FastMCP validates the call against `search_logs`'s Pydantic-derived schema and invokes the registered function in `tools/logs.py`.
3. **Auth resolution** - the tool wrapper calls `get_auth_instance()` and passes it to `_search_logs(..., auth=auth)`.
4. **Datadog call** - `_search_logs` builds a `LogsListRequest` (using `utils/time.parse_time_value` for `from_time`/`to_time`), calls `LogsApi.list_logs`, and parses each result with `LogEntry.model_validate(log.to_dict())`.
5. **Response finalization** - results are wrapped in `SearchLogsResponse` and passed through `finalize_list_response(result, "logs")`, which truncates and sets `count`/`warning` if the payload is too large.
6. **Return** - FastMCP serializes the `SearchLogsResponse` Pydantic model to both text and `structuredContent`; the agent receives it over stdio.

Errors take the same path but return early with `format_error_response(SearchLogsResponse, e, required_scope="logs_read")`, which never raises past the tool boundary - every tool call is dispatched, but a `success=False` response signals failure so the caller can inspect `error`.

## Testing architecture

- `tests/test_handshake.py` - boots the full server in-memory (`fastmcp.Client`), asserts the baseline tool/resource/prompt names are still present (guards against accidental renames), and round-trips one mocked tool call end-to-end.
- `tests/test_tool_schemas.py` - snapshots every tool's JSON input/output schema as a golden file; any shape drift shows up in a PR diff.
- `tests/tools/test_<domain>.py` - unit tests per domain calling `_function(...)` directly with mocked `datadog_api_client` classes and the `fake_auth` fixture.
- `tests/utils/` - unit tests for shared utilities (`parse_time_value`, response truncation, etc).
- Tests marked `@pytest.mark.live` make real, read-only Datadog API calls and are skipped by default (including in CI) - opt in with `pytest -m live` and real credentials.

## Security

- Credentials are never read from a committed file; `.env.example` documents local-dev-only usage, and the supported path is Cursor's `mcp.json` `env` block.
- Transport is local stdio - no network listener is opened by this server itself.
- All permissions are enforced by Datadog's RBAC on the configured app key; this server never requests scopes beyond what's documented in `docs/SCOPE_VERIFICATION.md`, and no tool performs a destructive `DELETE` (dashboards, monitors, and downtime cancellation are all excluded by design).

## Extension points

To add a new tool, extend an existing domain module or add a new `tools/<domain>.py`:

```python
# tools/<domain>.py
class MyToolResponse(ToolResponse):
    """Response for `my_new_tool`."""
    items: list[str] = Field(default_factory=list)

def _my_new_tool(query: str, auth: DatadogAuth) -> MyToolResponse:
    api_instance = get_api_instance(SomeApi, auth)
    try:
        response = api_instance.some_call(query)
        return MyToolResponse(items=[...])
    except Exception as e:  # noqa: BLE001
        return format_error_response(MyToolResponse, e, required_scope="some_scope")

def register_mydomain_tools(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def my_new_tool(query: str) -> MyToolResponse:
        """One-line summary.

        Use this when: ...

        Args:
            query: ...
        """
        return _my_new_tool(query, get_auth_instance())
```

Then call `register_mydomain_tools(mcp)` from `server.py`. Before writing the tool, verify the endpoint's required scope against the team's app key (see `docs/SCOPE_VERIFICATION.md` / `scripts/verify_scopes.py`) - this key is exclusive to this server and cannot be widened casually.

## File structure

```
datadog-mcp/
├── src/datadog_mcp/
│   ├── server.py               # Composition: registers all domains + resources/prompts
│   ├── auth.py                 # DatadogAuth singleton + get_auth_instance()
│   ├── tools/
│   │   ├── logs.py
│   │   ├── aggregations.py
│   │   ├── metrics.py
│   │   ├── dashboards.py
│   │   ├── apm.py
│   │   ├── monitors.py
│   │   └── downtimes.py
│   └── utils/
│       ├── auth.py             # get_api_instance() factory
│       ├── annotations.py      # ToolAnnotations presets
│       ├── pagination.py       # DEFAULT_PAGE_SIZE / MAX_PAGE_SIZE / clamp_page_size
│       ├── response.py         # DatadogModel, ToolResponse, PaginatedListResponse, etc.
│       └── time.py             # parse_time_value()
├── tests/
│   ├── test_handshake.py
│   ├── test_tool_schemas.py
│   ├── tools/                  # per-domain unit tests
│   └── utils/
├── scripts/verify_scopes.py    # Empirical scope verification against the real app key
├── docs/SCOPE_VERIFICATION.md  # Scope research + verification results
├── .github/workflows/ci.yml    # ruff + pyright + pytest on push/PR
├── .cursor/rules/               # Architecture/typing/documentation conventions for this repo
├── pyproject.toml
└── README.md
```

**Total tools**: 30 across 7 domains (logs, aggregations, metrics, dashboards, apm, monitors, downtimes), plus 2 resources and 4 prompts.
