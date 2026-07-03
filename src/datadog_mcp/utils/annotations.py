"""Honest `ToolAnnotations` presets shared across tool domains.

Centralizing these prevents two mistakes the adversarial review flagged in
the original plan: blanket `destructiveHint=False` on tools that actually
overwrite state with no undo, and inconsistent hints between near-identical
tools (e.g. one domain's "update" tool marked destructive and another's not).

All presets set `openWorldHint=True` since every tool here calls out to the
Datadog API (an "open world" system this server does not fully control).
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
"""Search/list/get tools: no state is changed in Datadog."""

WRITE_ADDITIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
"""Tools that create a new resource without touching existing ones
(create_new_dashboard, create_alert_monitor, schedule_downtime, send_custom_metric).
Not idempotent: calling twice creates two resources."""

WRITE_OVERWRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)
"""Tools that overwrite an existing resource's configuration with no revert
tool available (update_existing_dashboard, update_alert_monitor, update_downtime).
Marked destructive on purpose: the previous configuration is gone even though
nothing is "deleted" in the DELETE-verb sense. Idempotent: calling twice with
the same arguments converges on the same state."""

STATE_TOGGLE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
"""Reversible on/off toggles with a matching inverse tool
(silence_monitor/unsilence_monitor). Not destructive because the inverse
tool restores the prior behavior; idempotent because repeating the call
converges on the same state."""
