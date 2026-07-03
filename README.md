# Datadog MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that connects AI agents (Cursor, Claude, etc.) to Datadog. Search logs, query metrics, manage dashboards, analyze APM traces, and manage monitors/downtimes - all from your AI assistant, using the app key's real permissions.

Built with [FastMCP](https://gofastmcp.com) and Pydantic. No deletes, no destructive dashboard/monitor removal, and every tool response is a validated Pydantic model with a consistent `success`/`error` shape.

## Architecture

- **`server.py`** is a thin composition layer: it wires each domain's `register_<domain>_tools(mcp)` into one `FastMCP` instance and defines resources/prompts. It does not contain tool implementations.
- **`tools/*.py`** - one module per Datadog domain (logs, aggregations, metrics, apm, dashboards, monitors, downtimes). Each module owns its Pydantic models, its internal `_function(...)` implementation (auth injected explicitly, easy to unit test), and its `register_<domain>_tools(mcp)` function with the `@mcp.tool` decorators + docstrings.
- **`auth.py`** - the `DatadogAuth`/`get_auth_instance()` singleton. Same env vars as before (`DD_API_KEY`, `DD_APP_KEY`, `DD_SITE`); no auth behavior changed in this revamp.
- **`utils/response.py`** - shared Pydantic response infrastructure: inbound `DatadogModel` (tolerant, `extra="ignore"`) vs. outbound `ToolResponse`/`PaginatedListResponse` (strict, `extra="forbid"`), size-based truncation, and Datadog error classification (403 → missing scope, 429 → rate limit).
- **`utils/annotations.py`** - shared, honest `ToolAnnotations` presets (see the table below).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full request flow and [docs/SCOPE_VERIFICATION.md](docs/SCOPE_VERIFICATION.md) for the scope research behind every tool.

## Tools

All tool names, response field names, and env vars are stable across this revamp - nothing below was renamed. 30 tools total.

### 🔍 Logs
- **search_logs** - Search and view log entries (paginated)
- **get_log_details** - Full details of a single log by ID
- **count_logs** - Fast count of logs matching a query (no content transfer)
- **count_unique_values** - Count unique values of a field (e.g. distinct users)
- **aggregate_logs_by_field** - Group/aggregate logs with statistics; optional `interval` for a timeseries breakdown

### 📊 Metrics
- **query_metrics** - Query time series metrics with aggregations
- **list_available_metrics** - Discover metric names matching a prefix
- **list_active_metrics** - List metrics that reported data recently
- **describe_metric** - Metadata (unit, type, description) + known tags for one metric, in a single call
- **send_custom_metric** - Submit custom metrics (gauge, count, rate)

### 📈 Dashboards
- **list_all_dashboards** - Browse all dashboards
- **get_dashboard_details** - Complete dashboard config and widgets (large widget lists are truncated with a `warning`, see `finalize_list_response`)
- **create_new_dashboard** - Create a dashboard with widgets/layout (common widget types are pre-flight validated - see `datadog://widget-templates`)
- **update_existing_dashboard** - Modify an existing dashboard (overwrites given fields; no undo tool)

*No delete tool exists for dashboards, by design.*

### 🔬 APM / Traces
- **search_apm_traces** - Search spans by service, operation, tags
- **get_full_trace** - Full trace (all spans) by trace ID, via the dedicated per-trace endpoint
- **list_apm_services** - Discover instrumented services
- **aggregate_spans** - Latency/error statistics grouped by a facet, without pulling raw spans

### 🚨 Monitors
- **list_all_monitors** - List monitors with filters (state, name, tags)
- **search_monitors** - Full-text/faceted monitor search
- **get_monitor_details** - Full monitor configuration
- **validate_monitor** - Validate a monitor query/type before creating it
- **create_alert_monitor** - Create a metric, log, APM, or composite monitor
- **update_alert_monitor** - Modify an existing monitor's configuration
- **silence_monitor** / **unsilence_monitor** - Mute/unmute a single monitor (one-off; see downtimes for scheduled/scoped muting)

*No delete tool exists for monitors, by design.*

### 🌙 Downtimes
- **list_downtimes** - List scheduled/active downtimes
- **get_downtime** - Full details of one downtime
- **schedule_downtime** - Mute a scope of monitors (or one monitor) over a time window
- **update_downtime** - Modify an existing downtime's schedule/scope

*No `cancel_downtime` tool: it is a real, irreversible `DELETE` and is intentionally excluded pending explicit team sign-off (see `utils/annotations.py`).*

### Resources
- **`datadog://status`** - Quick health snapshot (alerting monitor count/names); makes exactly one Datadog API call
- **`datadog://widget-templates`** - Ready-to-use widget JSON for `create_new_dashboard`/`update_existing_dashboard` (timeseries, query_value, toplist, heatmap)

### Prompts
- **investigate_errors(service?, env, lookback)** - Guided error investigation across logs/APM/monitors
- **performance_analysis(service?, lookback)** - Guided latency/performance investigation
- **triage_alerting_monitors(env?)** - Prioritized triage of currently-alerting monitors
- **create_monitoring(target)** - Guided monitor + dashboard creation

### Tool safety annotations

Every tool declares an honest [`ToolAnnotations`](https://modelcontextprotocol.io/specification) hint via one of four presets in `utils/annotations.py`:

| Preset | readOnly | destructive | idempotent | Used by |
|---|---|---|---|---|
| `READ_ONLY` | ✅ | ❌ | ✅ | All search/list/get/count/aggregate/validate tools |
| `WRITE_ADDITIVE` | ❌ | ❌ | ❌ | `create_new_dashboard`, `create_alert_monitor`, `schedule_downtime`, `send_custom_metric` |
| `WRITE_OVERWRITE` | ❌ | ✅ | ✅ | `update_existing_dashboard`, `update_alert_monitor`, `update_downtime` (no undo tool exists, even though nothing is deleted) |
| `STATE_TOGGLE` | ❌ | ❌ | ✅ | `silence_monitor` / `unsilence_monitor` (reversible, matching inverse tool exists) |

## Installation

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended)
- A Datadog API key + Application key. The app key used by this server only needs (see [docs/SCOPE_VERIFICATION.md](docs/SCOPE_VERIFICATION.md) for the full rationale):
  - Read: `logs_read`, `metrics_read`, `dashboards_read`, `monitors_read`, `apm_read`
  - Write: `metrics_write`, `dashboards_write`, `monitors_write`, `monitors_downtime_write`

### 1. Install dependencies

```bash
cd /path/to/datadog-mcp
uv sync --frozen
```

`uv sync --frozen` installs exactly what's pinned in `uv.lock` - the same versions CI tests against. Only drop `--frozen` (and run `uv lock --upgrade` first) when intentionally bumping dependencies.

### 2. Configure Cursor's `mcp.json`

**Credentials belong in Cursor's `mcp.json`, not in this project.** The `.env.example` file at the repo root is for local development only (e.g. running `scripts/verify_scopes.py` directly).

```json
{
  "mcpServers": {
    "datadog": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/datadog-mcp",
        "run", "fastmcp", "run", "src/datadog_mcp/server.py"
      ],
      "env": {
        "DD_API_KEY": "${DD_API_KEY}",
        "DD_APP_KEY": "${DD_APP_KEY}",
        "DD_SITE": "datadoghq.com"
      }
    }
  }
}
```

Set `DD_API_KEY`/`DD_APP_KEY` in your shell profile and reference them with `${...}` as above, or inline the raw values directly in `mcp.json` (less secure, simpler).

**Datadog regions** (`DD_SITE`): `datadoghq.com` (US1, default), `us3.datadoghq.com`, `us5.datadoghq.com`, `datadoghq.eu`, `ap1.datadoghq.com`.

### 3. Restart Cursor

Restart Cursor IDE (or reload the MCP servers) to pick up the new server.

### Pinning a version for rollback

Cursor's `mcp.json` can point `--directory` at a specific git worktree/tag/commit. If a change to this server ever breaks the team, pin the `datadog-mcp` checkout to the last known-good tag/commit and re-run `uv sync --frozen` there - no code changes required to roll back.

## Development

### Running locally

```bash
uv run fastmcp run --reload src/datadog_mcp/server.py   # dev server with auto-reload
uv run datadog-mcp                                       # or: run the installed script directly
```

### Testing

```bash
uv run pytest                # unit + MCP handshake + tool-schema snapshot tests
uv run pytest -m live         # opt-in: real Datadog API calls, requires DD_API_KEY/DD_APP_KEY
```

- **Handshake test** (`tests/test_handshake.py`): boots the server in-memory via `fastmcp.Client`, asserts every baseline tool/resource/prompt name is still present, and round-trips a mocked tool call end-to-end. This is the safety net against an import error taking down the server for the whole team.
- **Schema snapshot tests** (`tests/test_tool_schemas.py`): every tool's input/output JSON schema is captured as a golden file; any shape change shows up in the PR diff instead of silently reaching the client. Regenerate intentionally-changed snapshots by running the test once with the update flag it defines, then reviewing the diff.
- **Live tests** (`pytest -m live`): a handful of read-only smoke calls gated behind real credentials, skipped by default (including in CI).

### Linting and type checking

```bash
uv run ruff check .
uv run ruff format .
uv run pyright src
uv run mypy src        # stricter, allowed to flag datadog-api-client's untyped calls (see inline `type: ignore[no-untyped-call]`)
```

CI (`.github/workflows/ci.yml`) runs ruff, `ruff format --check`, pyright, and pytest on every push/PR against the locked dependency set (`uv sync --frozen`). `pre-commit` runs the same ruff/pyright checks locally before commit.

### Adding a new tool

1. Add Pydantic request/response models and the `_function(...)` implementation to the relevant `tools/<domain>.py` (or a new domain module).
2. Register the `@mcp.tool(annotations=...)`-decorated wrapper inside that module's `register_<domain>_tools(mcp)`, with a docstring following the convention in [`.cursor/rules/documentation-standards.mdc`](.cursor/rules/documentation-standards.mdc).
3. Verify the required Datadog scope against `docs/SCOPE_VERIFICATION.md` / `scripts/verify_scopes.py` *before* writing the tool - this app key is exclusive to this server and has a fixed, narrow scope set.
4. Add a unit test under `tests/tools/`, then run the full suite - the handshake and schema snapshot tests will fail loudly if something regresses.

## Usage examples

```
Search Datadog logs for errors in the api service in the last hour
→ search_logs(query="status:error service:api", from_time="now-1h", to_time="now")

Show me CPU usage for all hosts over the last 4 hours
→ query_metrics(query="avg:system.cpu.user{*}", from_time="now-4h", to_time="now")

Create a dashboard called "API Performance" with a timeseries widget for request latency
→ create_new_dashboard(...) using a template from datadog://widget-templates

Mute all monitors in staging this weekend
→ schedule_downtime(scope="env:staging", ...)

What's currently alerting?
→ the triage_alerting_monitors prompt
```

## Troubleshooting

**Server not appearing in Cursor**
- Confirm the `--directory` path in `mcp.json` is absolute and correct.
- Confirm `DD_API_KEY`/`DD_APP_KEY` resolve to real values (check your shell profile if using `${...}` interpolation).
- Restart Cursor completely and check its MCP logs.

**Authentication / 403 errors**
- Tool responses classify 403s with the likely missing scope - check it against `docs/SCOPE_VERIFICATION.md`.
- Verify `DD_SITE` matches your Datadog region; a mismatched site behaves like an auth failure.

**Import errors after pulling changes**
```bash
uv sync --frozen
```

## API documentation

- [Datadog API Reference](https://docs.datadoghq.com/api/latest/)
- [Log Search Syntax](https://docs.datadoghq.com/logs/explorer/search_syntax/)
- [Metric Query Syntax](https://docs.datadoghq.com/dashboards/querying/)
- [Dashboard Widgets](https://docs.datadoghq.com/dashboards/widgets/)
- [Monitor Types](https://docs.datadoghq.com/monitors/types/)
- [FastMCP](https://gofastmcp.com)
- [Model Context Protocol](https://modelcontextprotocol.io)

## License

MIT License - See LICENSE file for details.
