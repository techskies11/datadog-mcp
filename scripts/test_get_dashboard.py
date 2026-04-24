#!/usr/bin/env python3
"""Smoke-test ``get_dashboard`` (raw JSON path) using ``.env`` in the repo root.

Usage (from repo root)::

    poetry run python scripts/test_get_dashboard.py
    poetry run python scripts/test_get_dashboard.py abc-xyz-123

Or with plain Python (adds ``src/`` to ``sys.path``)::

    python scripts/test_get_dashboard.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, cast


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_src_on_path(repo_root: Path) -> None:
    """Allow ``python scripts/...`` without an editable install."""
    src = repo_root / "src"
    if src.is_dir():
        src_str = str(src)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load DD_* from .env and call datadog_mcp get_dashboard once.",
    )
    parser.add_argument(
        "dashboard_id",
        nargs="?",
        default="zzz-zzz-zzz",
        help="Dashboard id (default: Internal Latency example id)",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    env_path = repo_root / ".env"
    _ensure_src_on_path(repo_root)

    from dotenv import load_dotenv

    if env_path.is_file():
        load_dotenv(env_path)
    else:
        load_dotenv()

    from datadog_mcp.tools.dashboards import get_dashboard

    result = cast(dict[str, Any], get_dashboard(args.dashboard_id))
    print(f"success: {result.get('success')}")
    if not result.get("success"):
        print(f"error: {result.get('error')}")
        return 1

    dashboard = result.get("dashboard")
    if not isinstance(dashboard, dict):
        print(f"error: unexpected dashboard type: {type(dashboard).__name__}")
        return 1

    widgets = dashboard.get("widgets")
    n_widgets = len(widgets) if isinstance(widgets, list) else 0
    print(f"title: {dashboard.get('title')!r}")
    print(f"id: {dashboard.get('id')!r}")
    print(f"widget_count: {n_widgets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
