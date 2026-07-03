"""Schema snapshot tests.

Captures the input/output JSON schema of every registered tool as a golden
file. Any accidental shape change (renamed parameter, changed type, removed
field) shows up as a diff here instead of surprising a teammate at runtime.

To intentionally update the snapshot after a deliberate schema change, run:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/test_tool_schemas.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from datadog_mcp.server import mcp

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "tool_schemas.json"


async def _current_schema_snapshot() -> dict[str, Any]:
    async with Client(mcp) as client:
        tools = await client.list_tools()

    snapshot: dict[str, Any] = {}
    for tool in sorted(tools, key=lambda t: t.name):
        snapshot[tool.name] = {
            "inputSchema": tool.inputSchema,
            "outputSchema": tool.outputSchema,
        }
    return snapshot


@pytest.mark.asyncio
async def test_tool_schemas_match_snapshot() -> None:
    """Fail loudly on any unreviewed change to a tool's input/output schema."""
    current = await _current_schema_snapshot()

    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        pytest.skip("Snapshot written/updated; re-run to verify.")

    saved = json.loads(SNAPSHOT_PATH.read_text())

    saved_names = set(saved.keys())
    current_names = set(current.keys())

    removed = saved_names - current_names
    assert not removed, f"Tools removed or renamed since last snapshot: {removed}"

    added = current_names - saved_names
    # Adding new tools is expected during this revamp; not a failure, just visible.
    if added:
        print(f"New tools since last snapshot: {sorted(added)}")

    changed = {
        name: {"before": saved[name], "after": current[name]}
        for name in saved_names & current_names
        if saved[name] != current[name]
    }
    assert not changed, (
        f"Schema changed for existing tools (breaking for MCP clients): "
        f"{json.dumps(changed, indent=2, default=str)}"
    )
