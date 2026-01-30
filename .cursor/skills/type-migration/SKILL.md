---
name: type-migration
description: Migrate Python code from loose typing to strict typing standards. Use when refactoring code to eliminate Any, add TypedDict, or improve type safety.
---

# Type Migration Guide

Systematically migrate Python code to strict typing standards with no `Any`, no untyped collections, and full type safety.

## Migration Strategy

### Phase 1: Audit Current State

Run type checker to identify issues:

```bash
# Install type checkers
uv add --dev mypy pyright

# Check current state
mypy src/
pyright src/
```

Create a list of files needing migration, prioritizing:
1. Core utilities (auth, response builders)
2. Tool implementations
3. Server routing layer

### Phase 2: Configure Strict Type Checking

Add to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.10"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_any_generics = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = "datadog_api_client.*"
ignore_missing_imports = true

[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.10"
reportMissingImports = true
reportMissingTypeStubs = false
```

### Phase 3: Systematic Migration

Follow this order for each file:

## Step 1: Update Imports

```python
# ❌ OLD - Remove these imports
from typing import List, Dict, Tuple, Optional, Union, Any

# ✅ NEW - Add these if needed
from typing import TypedDict, Literal, Final, TypeAlias, NotRequired
from collections.abc import Sequence, Mapping, Iterable, Callable
```

## Step 2: Replace Legacy Generic Types

```python
# ❌ OLD
def process(items: List[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for item in items:
        result[item] = len(item)
    return result

# ✅ NEW
def process(items: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        result[item] = len(item)
    return result
```

## Step 3: Replace Optional and Union

```python
# ❌ OLD
from typing import Optional, Union

def get_user(user_id: str) -> Optional[User]:
    pass

def parse(value: Union[str, int, float]) -> str:
    pass

# ✅ NEW
def get_user(user_id: str) -> User | None:
    pass

def parse(value: str | int | float) -> str:
    pass
```

## Step 4: Eliminate Any Types

### Strategy A: Use TypedDict for Structured Dicts

```python
# ❌ OLD
def search_logs(query: str) -> dict:
    return {
        "success": True,
        "logs": [...],
        "count": 10
    }

# ✅ NEW
from typing import TypedDict, NotRequired

class LogEntry(TypedDict):
    id: str
    message: str
    timestamp: str

class SearchLogsResponse(TypedDict):
    success: bool
    logs: list[LogEntry]
    count: int
    next_cursor: NotRequired[str | None]

def search_logs(query: str) -> SearchLogsResponse:
    return {
        "success": True,
        "logs": [...],
        "count": 10
    }
```

### Strategy B: Use object for JSON-like Data

```python
# ❌ OLD
def parse_json(data: Any) -> Any:
    pass

# ✅ NEW - Use object for truly dynamic data
def parse_json(data: object) -> object:
    """Parse JSON where structure is truly unknown."""
    pass

# ✅ BETTER - Define structure when possible
from typing import TypeAlias

JsonValue: TypeAlias = (
    str | int | float | bool | None 
    | dict[str, "JsonValue"] 
    | list["JsonValue"]
)

def parse_json(data: str) -> JsonValue:
    """Parse JSON with defined value types."""
    pass
```

### Strategy C: Use Generics for Flexible Functions

```python
# ❌ OLD
def get_api_instance(api_class, auth=None):
    pass

# ✅ NEW
from typing import TypeVar

T = TypeVar('T')

def get_api_instance(
    api_class: type[T],
    auth: DatadogAuth | None = None
) -> tuple[T, DatadogAuth]:
    if auth is None:
        auth = DatadogAuth()
    api_instance = api_class(auth.api_client)
    return api_instance, auth
```

## Step 5: Add Missing Return Types

```python
# ❌ OLD - Implicit return type
def process_data(items):
    return [item.upper() for item in items]

# ✅ NEW - Explicit return type
def process_data(items: Sequence[str]) -> list[str]:
    return [item.upper() for item in items]
```

## Step 6: Type Function Parameters

```python
# ❌ OLD - Untyped parameters
def calculate_stats(data, threshold=0.5):
    pass

# ✅ NEW - All parameters typed
def calculate_stats(
    data: Sequence[float],
    threshold: float = 0.5
) -> dict[str, float]:
    pass
```

## Step 7: Use Literal for Fixed Values

```python
# ❌ OLD - String without constraints
def set_level(level: str) -> None:
    pass

# ✅ NEW - Constrained values
from typing import Literal

def set_level(
    level: Literal["debug", "info", "warning", "error"]
) -> None:
    pass
```

## Step 8: Define Type Aliases

```python
# ✅ Create aliases for complex types
from typing import TypeAlias

UserId: TypeAlias = str
Timestamp: TypeAlias = int
DateMath: TypeAlias = str  # "now-1h"
TimeValue: TypeAlias = Timestamp | DateMath | str

QueryFilter: TypeAlias = dict[str, str | list[str]]
MetricQuery: TypeAlias = str  # "avg:system.cpu{*}"
```

## Common Migration Patterns

### Pattern 1: API Response Migration

```python
# ❌ BEFORE
def search_logs(query: str, from_time, to_time) -> dict:
    api = LogsApi(auth.api_client)
    response = api.list_logs(...)
    
    logs = []
    if response.data:
        for log in response.data:
            logs.append({
                "id": log.id,
                "message": log.attributes.message
            })
    
    return {
        "success": True,
        "logs": logs
    }

# ✅ AFTER
from typing import TypedDict, NotRequired

class LogEntry(TypedDict):
    id: str
    message: str | None
    timestamp: str | None

class SearchLogsResponse(TypedDict):
    success: bool
    logs: list[LogEntry]
    count: int
    error: NotRequired[str]

def search_logs(
    query: str,
    from_time: str,
    to_time: str
) -> SearchLogsResponse:
    api: LogsApi = LogsApi(auth.api_client)
    response: LogsListResponse = api.list_logs(...)
    
    logs: list[LogEntry] = []
    if response.data:
        for log in response.data:
            logs.append({
                "id": log.id if hasattr(log, 'id') else "",
                "message": log.attributes.message if hasattr(log.attributes, 'message') else None,
                "timestamp": log.attributes.timestamp.isoformat() if hasattr(log.attributes, 'timestamp') else None
            })
    
    return {
        "success": True,
        "logs": logs,
        "count": len(logs)
    }
```

### Pattern 2: Builder Class Migration

```python
# ❌ BEFORE
class ResponseBuilder:
    @staticmethod
    def success(data_key, data, **metadata):
        return {
            "success": True,
            data_key: data,
            **metadata
        }

# ✅ AFTER
from typing import Final

class ResponseBuilder:
    MAX_SIZE: Final[int] = 50_000
    
    @staticmethod
    def success(
        data_key: str,
        data: list[object],
        **metadata: object
    ) -> dict[str, object]:
        response: dict[str, object] = {
            "success": True,
            data_key: data,
            "count": len(data),
            **metadata
        }
        return ResponseBuilder._check_and_truncate(response, data_key)
```

### Pattern 3: Dependency Injection Migration

```python
# ❌ BEFORE
def search_logs(query, auth=None):
    if auth is None:
        auth = DatadogAuth()
    api_instance = LogsApi(auth.api_client)
    return api_instance.list_logs(...)

# ✅ AFTER
from typing import TypedDict

class SearchLogsResponse(TypedDict):
    success: bool
    logs: list[LogEntry]
    count: int

def search_logs(
    query: str,
    from_time: str,
    to_time: str,
    auth: DatadogAuth | None = None
) -> SearchLogsResponse:
    if auth is None:
        auth = DatadogAuth()
    api_instance: LogsApi = LogsApi(auth.api_client)
    # ... implementation
```

## Verification

After migration, verify with:

```bash
# Type check
mypy src/ --strict
pyright src/

# Should show 0 errors
```

## Migration Checklist per File

- [ ] Remove `Any` imports and usage
- [ ] Replace `List`, `Dict`, `Tuple`, `Optional`, `Union`
- [ ] Add TypedDict for all structured dict returns
- [ ] Add type hints to all function parameters
- [ ] Add return type to all functions
- [ ] Use `Literal` for fixed-value parameters
- [ ] Create TypeAlias for complex recurring types
- [ ] Use `collections.abc` for abstract types
- [ ] Add inline type annotations where helpful
- [ ] Run mypy/pyright with no errors

## Progressive Migration

If full migration is too large:

1. **Week 1**: Core utilities (auth.py, response.py, pagination.py)
2. **Week 2**: One tool domain (e.g., logs.py)
3. **Week 3**: Another tool domain (e.g., metrics.py)
4. **Week 4**: Server.py and remaining files

## Common Pitfalls

### Pitfall 1: Using object Everywhere

```python
# ❌ WRONG - object is not a catch-all
def process(data: object) -> object:
    return data["key"]  # Type error: object has no __getitem__

# ✅ RIGHT - Use proper types
def process(data: dict[str, str]) -> str:
    return data["key"]
```

### Pitfall 2: Over-Using Union

```python
# ❌ TOO BROAD
def process(value: str | int | float | list | dict | None) -> object:
    pass

# ✅ BE SPECIFIC
def process(value: str | int) -> str:
    return str(value)
```

### Pitfall 3: Forgetting NotRequired

```python
# ❌ WRONG - Optional fields as required
class Response(TypedDict):
    success: bool
    error: str | None  # This field is REQUIRED (must always be present)

# ✅ RIGHT - Truly optional fields
from typing import NotRequired

class Response(TypedDict):
    success: bool
    error: NotRequired[str]  # This field may be absent
```

## Summary

Type migration is systematic:
1. Configure strict type checking
2. Update imports (remove legacy typing)
3. Replace old generic syntax
4. Eliminate Any with TypedDict
5. Add all missing type hints
6. Use Literal and TypeAlias
7. Verify with mypy/pyright

Result: Complete type safety with zero `Any` types.
