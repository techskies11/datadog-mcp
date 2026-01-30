# Architecture Overview

## System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cursor IDE                              │
│                                                                 │
│  User: "Search for errors in API service from last hour"       │
│                                                                 │
│                            ↓                                    │
│                                                                 │
│                      AI Agent                                   │
│                                                                 │
│  Decides to use: search_logs tool                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                             ↓
                    MCP Protocol (stdio)
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Datadog MCP Server (Python)                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ server.py - MCP Server Entry Point                        │ │
│  │  • Registers 20 tools                                     │ │
│  │  • Routes tool calls to appropriate handlers              │ │
│  │  • Returns formatted JSON responses                       │ │
│  └───────────────────────────────────────────────────────────┘ │
│                             ↓                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ auth.py - Authentication Manager                          │ │
│  │  • Loads DD_API_KEY, DD_APP_KEY, DD_SITE                 │ │
│  │  • Configures Datadog API client                         │ │
│  │  • Manages regional endpoints                            │ │
│  └───────────────────────────────────────────────────────────┘ │
│                             ↓                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ tools/ - Tool Implementations                             │ │
│  │                                                           │ │
│  │  logs.py        → search_logs, get_log_details           │ │
│  │  metrics.py     → query_metrics, list_metrics, submit    │ │
│  │  dashboards.py  → CRUD operations for dashboards         │ │
│  │  apm.py         → search_spans, get_trace, list_services │ │
│  │  monitors.py    → CRUD + mute/unmute for monitors        │ │
│  │                                                           │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                             ↓
                      Datadog API Clients
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Datadog APIs                              │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Logs API │  │Metrics API│  │Dashboard│  │  APM API  │      │
│  │    v2    │  │  v1 / v2 │  │  API v1 │  │    v2     │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│                                                                 │
│  ┌──────────┐                                                  │
│  │Monitors │                                                   │
│  │ API v1  │                                                   │
│  └──────────┘                                                  │
│                                                                 │
│                     https://api.datadoghq.com                  │
│                   (or region-specific endpoint)                │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### Server Layer (`server.py`)
- **Framework**: MCP Python SDK
- **Transport**: stdio (standard input/output)
- **Tool Registration**: 20 tools across 5 categories
- **Response Format**: JSON with success/error handling

### Authentication Layer (`auth.py`)
- **Credentials**: API Key + Application Key
- **Configuration**: Regional endpoint support
- **Client Management**: Singleton pattern for API client
- **Environment**: Reads from .env file

### Tools Layer (`tools/*.py`)

#### Logs (`logs.py`)
- Uses Datadog API v2 LogsApi
- Supports query syntax, time ranges, facets
- Returns formatted log entries with metadata

#### Metrics (`metrics.py`)
- Uses v1 and v2 MetricsApi
- Query time series data
- Submit custom metrics (gauge, count, rate)
- List available metrics

#### Dashboards (`dashboards.py`)
- Uses Datadog API v1 DashboardsApi
- Full CRUD operations
- Support for complex widgets, variables, templates
- Layout types: ordered (timeline) and free (free-form)

#### APM (`apm.py`)
- Uses v2 SpansApi and TracesApi
- Search spans with query syntax
- Retrieve complete traces with all spans
- Service discovery

#### Monitors (`monitors.py`)
- Uses v1 MonitorsApi
- Support for all monitor types (metric, log, APM, composite)
- Full CRUD + mute/unmute operations
- Threshold configuration and notifications

## Data Flow Example

### Example: Search Logs

1. **User Input** (Cursor)
   ```
   "Find error logs in the api service from the last hour"
   ```

2. **AI Agent Decision**
   - Identifies need to use `search_logs` tool
   - Constructs parameters:
     - query: "status:error service:api"
     - from_time: ISO 8601 timestamp (1 hour ago)
     - to_time: ISO 8601 timestamp (now)

3. **MCP Server** (`server.py`)
   - Receives tool call via stdio
   - Routes to `search_logs()` function
   - Passes parameters

4. **Auth Manager** (`auth.py`)
   - Provides authenticated API client
   - Configures regional endpoint

5. **Logs Tool** (`logs.py`)
   - Creates LogsListRequest with query filter
   - Calls Datadog API v2
   - Parses response

6. **Datadog API**
   - Searches log indexes
   - Returns matching logs

7. **Response Flow**
   - Tool formats logs as JSON
   - Server wraps in TextContent
   - Returns via stdio to Cursor
   - AI Agent presents to user

## Security

- **Credentials**: Stored in .env file (not committed)
- **API Keys**: Loaded from environment variables
- **Transport**: Local stdio, no network exposure
- **Permissions**: Respects Datadog RBAC

## Performance

- **Connection**: Reuses API client configuration
- **Pagination**: Supports limits on all list operations
- **Async**: MCP server runs asynchronously
- **Efficiency**: Direct API calls, no caching layer

## Error Handling

All tools return structured responses:
```json
{
  "success": true/false,
  "data": {...},
  "error": "error message if failed"
}
```

## Extension Points

Want to add more tools?

1. **Add function** to appropriate tool file
2. **Register tool** in `server.py` `list_tools()`
3. **Add handler** in `server.py` `call_tool()`

Example:
```python
# In tools/logs.py
def get_log_archives():
    # Implementation
    pass

# In server.py
@app.list_tools()
async def list_tools():
    tools.append(Tool(
        name="get_log_archives",
        description="...",
        inputSchema={...}
    ))

@app.call_tool()
async def call_tool(name, arguments):
    if name == "get_log_archives":
        result = get_log_archives(**arguments)
```

## File Structure

```
datadog-mcp/
├── src/datadog_mcp/
│   ├── __init__.py          # Package initialization
│   ├── server.py            # 700+ lines - MCP server core
│   ├── auth.py              # 70 lines - Authentication
│   └── tools/
│       ├── __init__.py      # Package initialization
│       ├── logs.py          # 130 lines - 2 tools
│       ├── metrics.py       # 180 lines - 3 tools
│       ├── dashboards.py    # 250 lines - 5 tools
│       ├── apm.py           # 200 lines - 3 tools
│       └── monitors.py      # 350 lines - 7 tools
├── pyproject.toml           # Dependencies & project config
├── .env.example             # Credentials template
├── setup.sh                 # Automated setup script
├── README.md                # Complete documentation
├── QUICKSTART.md            # 5-minute setup guide
├── EXAMPLES.md              # Usage examples & recipes
└── cursor-mcp-config.json   # Ready-to-use Cursor config
```

**Total Code**: ~1,900 lines of Python
**Total Tools**: 20 tools across 5 categories
**API Coverage**: Logs, Metrics, Dashboards, APM, Monitors
