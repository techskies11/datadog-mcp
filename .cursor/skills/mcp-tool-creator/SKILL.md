---
name: mcp-tool-creator
description: Create new MCP tools following FastMCP best practices and strict typing standards. Use when adding new tools or endpoints to the Datadog MCP server.
---

# MCP Tool Creator

This skill guides you through creating new MCP tools for the Datadog MCP server with proper typing, documentation, and architecture.

## Step-by-Step Tool Creation

### Step 1: Plan the Tool

Before writing code, determine:

1. **Purpose**: What specific task does this tool accomplish?
2. **API Endpoint**: Which Datadog API endpoint(s) will it use?
3. **Parameters**: What inputs does it need?
4. **Return Type**: What data structure will it return?
5. **Domain**: Which tool file should contain it? (logs, metrics, dashboards, apm, monitors, or new domain)

### Step 2: Define TypedDict Response Structure

Create explicit types before implementation:

```python
from typing import TypedDict, NotRequired

class ToolResponse(TypedDict):
    """Response from the new tool."""
    success: bool
    error: NotRequired[str]
    # Add specific fields for your tool
    data: list[DataItem]
    count: int
    next_cursor: NotRequired[str | None]
```

### Step 3: Create Internal Implementation

In the appropriate `tools/*.py` file:

```python
"""Module docstring describing this domain."""

from typing import TypedDict, Literal, NotRequired
from datadog_api_client.v2.api.relevant_api import RelevantApi
from datadog_api_client.v2.model.request_model import RequestModel

from ..auth import DatadogAuth
from ..utils.response import ResponseBuilder, format_error_response
from ..utils.auth import get_api_instance

# Define response types first
class ItemData(TypedDict):
    """Individual item in response."""
    id: str
    name: str
    value: int

class ToolResponse(TypedDict):
    """Complete tool response."""
    success: bool
    data: list[ItemData]
    count: int
    error: NotRequired[str]

# Implementation function
def my_new_tool(
    param1: str,
    param2: int | None = None,
    auth: DatadogAuth | None = None
) -> ToolResponse:
    """Internal implementation with business logic.

    Args:
        param1: Description of parameter 1
        param2: Description of parameter 2 (optional)
        auth: DatadogAuth instance (injected)

    Returns:
        ToolResponse with data and metadata
    """
    # Get API instance
    api_instance, auth = get_api_instance(RelevantApi, auth)

    try:
        # Build API request
        request = RequestModel(
            param1=param1,
            param2=param2
        )

        # Call API
        response = api_instance.call_endpoint(body=request)

        # Format data
        items: list[ItemData] = []
        if hasattr(response, 'data') and response.data:
            for item in response.data:
                items.append({
                    "id": item.id if hasattr(item, 'id') else "",
                    "name": item.name if hasattr(item, 'name') else "",
                    "value": item.value if hasattr(item, 'value') else 0
                })

        # Use ResponseBuilder for auto-truncation
        return ResponseBuilder.success("data", items)

    except Exception as e:
        return format_error_response("data", e)
```

### Step 4: Add FastMCP Tool Decorator in server.py

```python
# In server.py
from datadog_mcp.tools.domain import my_new_tool as _my_new_tool

@mcp.tool()
def my_new_tool(
    param1: str,
    param2: int | None = None
) -> dict[str, object]:
    """One-line summary of what this tool does.

    ⚠️ IMPORTANT USAGE NOTES: When to use this tool vs alternatives.

    Use this when:
    - Specific use case 1
    - Specific use case 2

    DO NOT use for:
    - Alternative tool 1 (use other_tool instead)
    - Alternative tool 2 (use another_tool instead)

    Args:
        param1: Clear description with examples (e.g., "user_id" or "email@example.com")
        param2: Clear description with range/constraints (default: None, range: 1-100)

    Returns:
        dict with success flag, data array, and count

    Examples:
        my_new_tool("value1")
        my_new_tool("value1", param2=50)
    """
    auth = get_auth_instance()
    return _my_new_tool(param1, param2, auth=auth)
```

### Step 5: Validation Checklist

Before committing, verify:

**Typing**:
- [ ] No `Any` types
- [ ] All `dict` and `list` have type parameters
- [ ] TypedDict defined for response structure
- [ ] Function signature has complete type hints
- [ ] Using Python 3.10+ syntax (no `List`, `Dict`, `Optional`)

**Documentation**:
- [ ] Tool has comprehensive docstring
- [ ] Includes "Use this when" section
- [ ] Includes "DO NOT use for" section
- [ ] All parameters documented with examples
- [ ] Return value documented
- [ ] Usage examples provided

**Architecture**:
- [ ] Implementation in `tools/*.py` file
- [ ] FastMCP decorator in `server.py`
- [ ] Uses `ResponseBuilder.success()`
- [ ] Uses `format_error_response()` for errors
- [ ] Follows dependency injection pattern

**Safety**:
- [ ] Tool is read-focused (GET-equivalent)
- [ ] Destructive operations require confirmation
- [ ] Input validation implemented
- [ ] Error handling comprehensive

## Tool Naming Guidelines

Choose clear, consistent names:

```python
# ✅ GOOD
search_logs()
query_metrics()
list_dashboards()
create_dashboard()
delete_monitor()
count_logs()

# ❌ BAD
searchDatadogLogsWithQuerySyntax()  # Too verbose
search()  # Too vague
get_stuff()  # Unclear
```

**Pattern**: `verb_noun` (e.g., `search_logs`, `create_dashboard`, `count_metrics`)

## Common Patterns

### Pattern 1: Search/List Tool

```python
def search_items(
    query: str,
    page_size: int = 25,
    cursor: str | None = None,
    auth: DatadogAuth | None = None
) -> dict[str, object]:
    """Search with pagination."""
    from ..utils.pagination import validate_page_size

    page_size = validate_page_size(page_size)
    api_instance, auth = get_api_instance(ItemsApi, auth)

    try:
        response = api_instance.search(query=query, limit=page_size, cursor=cursor)

        items = [format_item(item) for item in response.data]

        return ResponseBuilder.success(
            "items",
            items,
            next_cursor=response.next_cursor if hasattr(response, 'next_cursor') else None,
            has_more=response.has_more if hasattr(response, 'has_more') else False
        )
    except Exception as e:
        return format_error_response("items", e)
```

### Pattern 2: Aggregation/Count Tool

```python
def count_items(
    query: str,
    from_time: str,
    to_time: str,
    auth: DatadogAuth | None = None
) -> dict[str, object]:
    """Count without fetching data."""
    api_instance, auth = get_api_instance(ItemsApi, auth)

    try:
        response = api_instance.aggregate(
            query=query,
            from_time=from_time,
            to_time=to_time,
            aggregation="count"
        )

        count = extract_count(response)

        return {
            "success": True,
            "count": count,
            "query": query
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "count": 0
        }
```

### Pattern 3: Create/Update Tool

```python
def create_item(
    name: str,
    config: dict[str, str | int | bool],
    tags: list[str] | None = None,
    auth: DatadogAuth | None = None
) -> dict[str, object]:
    """Create new item."""
    api_instance, auth = get_api_instance(ItemsApi, auth)

    try:
        request = CreateItemRequest(
            name=name,
            config=config,
            tags=tags or []
        )

        response = api_instance.create(body=request)

        return {
            "success": True,
            "item_id": response.id,
            "url": response.url if hasattr(response, 'url') else None
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
```

## Integration Testing

After creating the tool, test it:

```python
# Manual test
from datadog_mcp.tools.domain import my_new_tool
from datadog_mcp.auth import DatadogAuth

auth = DatadogAuth()
result = my_new_tool("test_param", auth=auth)
print(result)
```

## Documentation Updates

Update the README.md with the new tool:

```markdown
### Domain Name
- **my_new_tool** - Brief description of what it does and when to use it
```

## Summary

Creating a new tool requires:

1. Define TypedDict response structure
2. Implement in `tools/*.py` with full typing
3. Add FastMCP decorator in `server.py` with rich docs
4. Use ResponseBuilder and format_error_response
5. Follow dependency injection pattern
6. Test manually
7. Update README.md

This ensures consistency, type safety, and excellent developer experience.
