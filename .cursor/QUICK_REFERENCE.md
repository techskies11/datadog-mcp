# Type Safety & Best Practices - Quick Reference

This document provides a quick reference for the typing and MCP best practices in this project.

## 🚫 Never Use

```python
# ❌ FORBIDDEN
from typing import Any, List, Dict, Optional, Union

def bad_function(data: Any) -> dict:  # Untyped dict
    pass

def another_bad(items: list) -> List[str]:  # Untyped list + legacy syntax
    pass
```

## ✅ Always Use

```python
# ✅ CORRECT
from typing import TypedDict, Literal, NotRequired, TypeAlias
from collections.abc import Sequence, Mapping

class ResponseData(TypedDict):
    success: bool
    items: list[str]
    count: int
    error: NotRequired[str]  # Optional field

def good_function(data: dict[str, int]) -> ResponseData:
    pass

def another_good(items: Sequence[str]) -> list[str]:
    pass
```

## Type Patterns Cheat Sheet

### Collections
```python
list[str]                    # List of strings
dict[str, int]               # String keys, int values
set[int]                     # Set of integers
tuple[str, int, bool]        # Fixed-size tuple
Sequence[str]                # Accept any sequence (param)
Mapping[str, int]            # Accept any mapping (param)
```

### Unions and Optionals
```python
str | int | float            # Union (multiple types)
User | None                  # Optional (was Optional[User])
```

### Literal Values
```python
Literal["debug", "info", "error"]  # Only these exact values
```

### TypedDict
```python
class User(TypedDict):
    id: str
    name: str
    age: int
    email: NotRequired[str]  # May be absent from dict
```

### Type Aliases
```python
UserId: TypeAlias = str
JsonValue: TypeAlias = str | int | float | bool | None
```

## FastMCP Tool Template

```python
# In server.py
@mcp.tool()
def tool_name(
    param1: str,
    param2: int = 10
) -> dict[str, object]:
    """One-line summary of what this tool does.
    
    ⚠️ IMPORTANT: When to use this vs alternatives.
    
    Use this when:
    - Specific scenario 1
    - Specific scenario 2
    
    DO NOT use for:
    - Use other_tool instead
    
    Args:
        param1: Description with example (e.g., "user_id" or "email@example.com")
        param2: Description with range (default: 10, range: 1-100)
    
    Returns:
        dict with success, data, and count fields
    
    Examples:
        tool_name("value1")
        tool_name("value1", param2=50)
    """
    auth = get_auth_instance()
    return _tool_name(param1, param2, auth=auth)


# In tools/domain.py
from typing import TypedDict, NotRequired

class ToolResponse(TypedDict):
    success: bool
    data: list[DataItem]
    count: int
    error: NotRequired[str]

def _tool_name(
    param1: str,
    param2: int,
    auth: DatadogAuth
) -> ToolResponse:
    """Internal implementation."""
    api_instance, auth = get_api_instance(RelevantApi, auth)
    
    try:
        response = api_instance.call(param1=param1)
        items = [format_item(item) for item in response.data]
        
        return ResponseBuilder.success("data", items)
    except Exception as e:
        return format_error_response("data", e)
```

## Common Patterns

### Pattern: API Response Formatting
```python
class LogEntry(TypedDict):
    id: str
    message: str | None
    timestamp: str | None

def format_log(log: Log) -> LogEntry:
    return {
        "id": log.id if hasattr(log, 'id') else "",
        "message": log.attributes.message if hasattr(log.attributes, 'message') else None,
        "timestamp": log.attributes.timestamp.isoformat() if hasattr(log.attributes, 'timestamp') else None
    }
```

### Pattern: Pagination
```python
def search_items(
    query: str,
    page_size: int = 25,
    cursor: str | None = None,
    auth: DatadogAuth | None = None
) -> dict[str, object]:
    page_size = min(page_size, MAX_PAGE_SIZE)
    
    response = api.search(query, limit=page_size, cursor=cursor)
    
    return ResponseBuilder.success(
        "items",
        response.items,
        next_cursor=response.next_cursor,
        has_more=response.has_more
    )
```

### Pattern: Error Handling
```python
try:
    result = api.call()
    return ResponseBuilder.success("data", result)
except ApiException as e:
    return format_error_response("data", e)
```

## Type Checking Commands

```bash
# Install dev dependencies
uv add --dev mypy pyright pytest

# Run type checkers
mypy src/ --strict
pyright src/

# Should show 0 errors!
```

## File Organization

```
datadog-mcp/
├── src/datadog_mcp/
│   ├── server.py          # FastMCP routing only
│   ├── auth.py            # Auth singleton
│   ├── tools/
│   │   ├── logs.py        # Log tools implementation
│   │   ├── metrics.py     # Metric tools implementation
│   │   └── ...
│   └── utils/
│       ├── auth.py        # Auth helpers
│       ├── response.py    # Response builders
│       └── pagination.py  # Constants
└── .cursor/
    ├── rules/             # Coding standards
    ├── skills/            # Development workflows
    └── agents/            # Code reviewers
```

## Resources Created

### Rules (`.cursor/rules/`)
1. **python-typing.mdc** - Strict typing standards
2. **fastmcp-best-practices.mdc** - MCP server patterns
3. **mcp-architecture.mdc** - Architecture patterns
4. **documentation-standards.mdc** - Documentation requirements

### Skills (`.cursor/skills/`)
1. **mcp-tool-creator/** - Guide for creating new tools
2. **type-migration/** - Guide for migrating to strict types

### Agents (`.cursor/agents/`)
1. **mcp-type-guardian.md** - Code quality enforcer

## Pre-Commit Checklist

Before committing code:
- [ ] No `Any` types anywhere
- [ ] All `dict` and `list` have type parameters
- [ ] All functions have complete type hints
- [ ] TypedDict defined for structured returns
- [ ] Using Python 3.10+ syntax (no legacy typing)
- [ ] Tool has comprehensive docstring with examples
- [ ] `mypy src/ --strict` passes with 0 errors
- [ ] `pyright src/` passes with 0 errors
- [ ] Code follows separation: server.py (routing) vs tools/ (logic)

## Getting Help

- **Typing issues?** Read `.cursor/rules/python-typing.mdc`
- **FastMCP patterns?** Read `.cursor/rules/fastmcp-best-practices.mdc`
- **Architecture questions?** Read `.cursor/rules/mcp-architecture.mdc`
- **Adding a tool?** Use skill: `mcp-tool-creator`
- **Migrating types?** Use skill: `type-migration`
- **Code review?** Invoke agent: `mcp-type-guardian`

## Quick Fixes

### Fix: Untyped dict return
```python
# Before
def search() -> dict:
    return {"success": True, "data": [...]}

# After
class SearchResponse(TypedDict):
    success: bool
    data: list[Item]

def search() -> SearchResponse:
    return {"success": True, "data": [...]}
```

### Fix: Legacy typing imports
```python
# Before
from typing import List, Dict, Optional

def process(items: List[str]) -> Optional[Dict[str, int]]:
    pass

# After
def process(items: list[str]) -> dict[str, int] | None:
    pass
```

### Fix: Any usage
```python
# Before
def process(data: Any) -> Any:
    return data

# After - Define proper types
class InputData(TypedDict):
    id: str
    value: int

class OutputData(TypedDict):
    result: str

def process(data: InputData) -> OutputData:
    return {"result": str(data["value"])}
```

---

**Remember**: Strict typing catches bugs before runtime and makes the code self-documenting. No compromises!
