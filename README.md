# Datadog MCP Server

A Model Context Protocol (MCP) server that connects Cursor AI agents to Datadog APIs. Search logs, query metrics, manage dashboards, analyze APM traces, and control monitors - all from your AI assistant.

## Architecture

This project uses **FastMCP** (Fast Model Context Protocol) for elegant, FastAPI-style tool definitions. Tools are automatically discovered via decorators, schemas are generated from type hints, and routing is handled automatically.

Key patterns:
- **Dependency Injection**: Like FastAPI, auth is injected into tools
- **No Context Managers**: Direct API client access for simplicity
- **Resources**: Proactive context for the AI agent
- **Prompts**: Pre-configured query templates

See [FASTMCP_IMPROVEMENTS.md](FASTMCP_IMPROVEMENTS.md) for details on agent detection improvements and [DEPENDENCY_INJECTION.md](DEPENDENCY_INJECTION.md) for architecture patterns.

## Features

### 🔍 Logs
- **search_logs** - Search logs with Datadog query syntax, time ranges, and facets
- **get_log_details** - Get detailed information about specific log entries

### 📊 Metrics
- **query_metrics** - Query time series metrics with aggregations
- **list_metrics** - Discover available metrics
- **submit_metrics** - Send custom metrics (gauge, count, rate)

### 📈 Dashboards
- **list_dashboards** - Browse all dashboards
- **get_dashboard** - Get complete dashboard definitions
- **create_dashboard** - Create dashboards with widgets, variables, and templates
- **update_dashboard** - Modify existing dashboards
- **delete_dashboard** - Remove dashboards

### 🔬 APM/Traces
- **search_spans** - Search APM spans by service, operation, tags
- **get_trace** - Get complete trace information with all spans
- **list_services** - List available APM services

### 🚨 Monitors/Alerts
- **list_monitors** - List all monitors with filtering
- **get_monitor** - Get monitor details
- **create_monitor** - Create metric, log, APM, or composite monitors
- **update_monitor** - Modify monitor configuration
- **delete_monitor** - Remove monitors
- **mute_monitor** / **unmute_monitor** - Control alert notifications

## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Datadog account with API access

### 1. Install Dependencies

Using uv (recommended):
```bash
cd /path/to/datadog-mcp
uv sync
```

Using pip:
```bash
pip install -e .
```

### 2. Configure Datadog Credentials

**⚠️ IMPORTANT: Credentials go in Cursor's mcp.json, NOT in this project's .env**

#### Option A: Using Environment Variables (Recommended)

Set these in your shell's RC file (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
export DD_API_KEY="your-api-key-here"
export DD_APP_KEY="your-application-key-here"
export DD_SITE="datadoghq.com"
```

Then in Cursor's `mcp.json`, reference them:

```json
{
  "mcpServers": {
    "datadog": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/datadog-mcp", "run", "fastmcp", "run", "src/datadog_mcp/server.py"],
      "env": {
        "DD_API_KEY": "${DD_API_KEY}",
        "DD_APP_KEY": "${DD_APP_KEY}",
        "DD_SITE": "${DD_SITE}"
      }
    }
  }
}
```

#### Option B: Direct in mcp.json

Alternatively, put credentials directly in Cursor's `mcp.json` (less secure, but simpler):

```json
{
  "mcpServers": {
    "datadog": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/datadog-mcp", "run", "fastmcp", "run", "src/datadog_mcp/server.py"],
      "env": {
        "DD_API_KEY": "your-actual-api-key",
        "DD_APP_KEY": "your-actual-app-key",
        "DD_SITE": "datadoghq.com"
      }
    }
  }
}
```

#### Getting Your API Keys

1. Go to [Datadog Organization Settings](https://app.datadoghq.com/organization-settings/api-keys)
2. **API Key**: Organization Settings > API Keys > New Key
3. **Application Key**: Organization Settings > Application Keys > New Key

**🔐 Important**: The Application Key requires specific scopes for full functionality:
- Read: `logs_read`, `metrics_read`, `dashboards_read`, `monitors_read`, `apm_read`
- Write: `metrics_write`, `dashboards_write`, `monitors_write`, `monitors_downtime_write`

**See [DATADOG_PERMISSIONS.md](DATADOG_PERMISSIONS.md) for detailed permission requirements.**

#### Datadog Regions

Set `DD_SITE` based on your Datadog region:
- US1: `datadoghq.com` (default)
- US3: `us3.datadoghq.com`
- US5: `us5.datadoghq.com`
- EU: `datadoghq.eu`
- AP1: `ap1.datadoghq.com`

### 3. Configure Cursor

Add the Datadog MCP server to Cursor's MCP configuration:

**Location:**
- macOS/Linux: `~/.cursor/mcp.json`
- Windows: `%APPDATA%\Cursor\mcp.json`

**Configuration:**

```json
{
  "mcpServers": {
    "datadog": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/datadog-mcp",
        "run",
        "fastmcp",
        "run",
        "src/datadog_mcp/server.py"
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

**Important**: Replace `/absolute/path/to/datadog-mcp` with the actual absolute path to this project.

### 4. Restart Cursor

Restart Cursor IDE to load the new MCP server.

## Usage Examples

### Search Logs

```
Search Datadog logs for errors in the api service in the last hour
```

The agent will use `search_logs` with appropriate query syntax like:
- Query: `status:error service:api`
- Time range: last hour in ISO 8601 format

### Query Metrics

```
Show me CPU usage for all hosts over the last 4 hours
```

The agent will use `query_metrics` with:
- Query: `avg:system.cpu.user{*}`
- Time range: Unix timestamps for last 4 hours

### Create a Dashboard

```
Create a dashboard called "API Performance" with a timeseries widget showing request latency
```

The agent will use `create_dashboard` with proper widget configuration.

### Search APM Traces

```
Find traces for the checkout service with status code 500 in the last 30 minutes
```

The agent will use `search_spans` with:
- Query: `service:checkout @http.status_code:500`
- Time range: last 30 minutes

### Create a Monitor

```
Create a metric alert that notifies @slack-alerts when CPU usage exceeds 80%
```

The agent will use `create_monitor` with appropriate thresholds and notification settings.

## Development

### Project Structure

```
datadog-mcp/
├── src/
│   └── datadog_mcp/
│       ├── __init__.py
│       ├── server.py           # MCP server entry point
│       ├── auth.py             # Authentication management
│       └── tools/
│           ├── logs.py         # Logs tools
│           ├── metrics.py      # Metrics tools
│           ├── dashboards.py   # Dashboard tools
│           ├── apm.py          # APM/traces tools
│           └── monitors.py     # Monitor tools
├── pyproject.toml
├── README.md
└── .env.example
```

### Running Locally

Test the server directly:

```bash
# Using uv
uv run datadog-mcp

# Using python
python -m datadog_mcp.server
```

### Adding New Tools

1. Implement the tool function in the appropriate file under `src/datadog_mcp/tools/`
2. Add the tool definition to `list_tools()` in `server.py`
3. Add the tool handler to `call_tool()` in `server.py`

## Troubleshooting

### Server Not Appearing in Cursor

1. Check that the path in `mcp.json` is absolute and correct
2. Ensure credentials are set in `.env` or environment variables
3. Restart Cursor IDE completely
4. Check Cursor logs for MCP server errors

### Authentication Errors

1. Verify API keys are correct in `.env`
2. Check that Application Key has proper permissions
3. Verify `DD_SITE` matches your Datadog region

### Import Errors

```bash
# Reinstall dependencies
uv sync
# or
pip install -e .
```

## API Documentation

For detailed information about Datadog API endpoints and query syntax:

- [Datadog API Reference](https://docs.datadoghq.com/api/latest/)
- [Log Search Syntax](https://docs.datadoghq.com/logs/explorer/search_syntax/)
- [Metric Query Syntax](https://docs.datadoghq.com/dashboards/querying/)
- [Dashboard Widgets](https://docs.datadoghq.com/dashboards/widgets/)
- [Monitor Types](https://docs.datadoghq.com/monitors/types/)

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

MIT License - See LICENSE file for details
