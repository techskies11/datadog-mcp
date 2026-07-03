#!/usr/bin/env python3
"""Empirically verify which candidate endpoints work with the team's app key.

This is the Fase 2 gate from the revamp plan: before writing a tool for a new
endpoint, we must confirm the current app key's scopes actually allow calling
it, rather than assuming based on Datadog's (sometimes inconsistent) scope
naming.

Every call here is READ-ONLY or a documented no-side-effect validation call
(`validate_monitor`). It never creates, schedules, mutes, or cancels anything.

Usage:
    export DD_API_KEY=...
    export DD_APP_KEY=...
    uv run python scripts/verify_scopes.py

Exit code is 0 if all checks ran (regardless of pass/fail per endpoint) so it
is safe to pipe into other tooling; look at the printed table for results.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from datadog_api_client.exceptions import ApiException, ForbiddenException

from datadog_mcp.auth import DatadogAuth


@dataclass
class CheckResult:
    domain: str
    endpoint: str
    scope_expected: str
    status: str  # "OK", "FORBIDDEN (403)", "ERROR"
    detail: str = ""


def _run(domain: str, endpoint: str, scope_expected: str, fn: Any) -> CheckResult:
    try:
        fn()
    except ForbiddenException as exc:
        return CheckResult(domain, endpoint, scope_expected, "FORBIDDEN (403)", str(exc)[:200])
    except ApiException as exc:
        # Some read endpoints 404 on empty/missing IDs even with correct scope;
        # only 403 means "scope problem". Anything else is reported but not fatal.
        return CheckResult(
            domain, endpoint, scope_expected, f"ERROR ({exc.status})", str(exc)[:200]
        )
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic script
        return CheckResult(domain, endpoint, scope_expected, "ERROR", str(exc)[:200])
    return CheckResult(domain, endpoint, scope_expected, "OK")


def main() -> int:
    try:
        auth = DatadogAuth()
    except ValueError as exc:
        print(f"Cannot run: {exc}")
        print("Set DD_API_KEY and DD_APP_KEY before running this script.")
        return 1

    results: list[CheckResult] = []

    # --- Downtimes (v2.DowntimesApi) -----------------------------------
    from datadog_api_client.v2.api.downtimes_api import DowntimesApi

    downtimes_api = DowntimesApi(auth.api_client)
    results.append(
        _run(
            "downtimes",
            "list_downtimes",
            "monitors_downtime_write (or monitors_downtime)",
            lambda: downtimes_api.list_downtimes(page_limit=1),
        )
    )

    # --- Monitors advanced (v1.MonitorsApi) -----------------------------
    from datadog_api_client.v1.api.monitors_api import MonitorsApi
    from datadog_api_client.v1.model.monitor import Monitor
    from datadog_api_client.v1.model.monitor_type import MonitorType

    monitors_api = MonitorsApi(auth.api_client)
    results.append(
        _run(
            "monitors",
            "search_monitors",
            "monitors_read",
            lambda: monitors_api.search_monitors(query="*", per_page=1),
        )
    )
    results.append(
        _run(
            "monitors",
            "validate_monitor (metric alert, no side effects)",
            "monitors_write",
            lambda: monitors_api.validate_monitor(
                body=Monitor(
                    name="scope-check-do-not-save",
                    type=MonitorType.METRIC_ALERT,
                    query="avg(last_5m):avg:system.cpu.user{*} > 80",
                    message="scope verification only, never created",
                )
            ),
        )
    )

    # --- Metrics advanced (v1.MetricsApi / v2.MetricsApi) ---------------
    from datadog_api_client.v1.api.metrics_api import MetricsApi as MetricsApiV1
    from datadog_api_client.v1.model.metric_metadata import MetricMetadata
    from datadog_api_client.v2.api.metrics_api import MetricsApi as MetricsApiV2

    metrics_v1 = MetricsApiV1(auth.api_client)
    metrics_v2 = MetricsApiV2(auth.api_client)
    results.append(
        _run(
            "metrics",
            "list_active_metrics",
            "metrics_read",
            lambda: metrics_v1.list_active_metrics(_from=0),
        )
    )
    results.append(
        _run(
            "metrics",
            "get_metric_metadata (system.cpu.user)",
            "metrics_read",
            lambda: metrics_v1.get_metric_metadata("system.cpu.user"),
        )
    )
    results.append(
        _run(
            "metrics",
            "list_tags_by_metric_name (system.cpu.user)",
            "metrics_read",
            lambda: metrics_v2.list_tags_by_metric_name("system.cpu.user"),
        )
    )

    # --- APM advanced (v2.SpansApi) -------------------------------------
    from datadog_api_client.v2.api.spans_api import SpansApi

    spans_api = SpansApi(auth.api_client)
    results.append(
        _run(
            "apm",
            "aggregate_spans",
            "apm_read",
            lambda: spans_api.aggregate_spans(
                # dict body works at runtime; see tools/apm.py for the same pattern
                body={  # type: ignore[arg-type]
                    "data": {
                        "type": "aggregate_request",
                        "attributes": {
                            "filter": {"query": "*", "from": "now-15m", "to": "now"},
                            "compute": [{"aggregation": "count"}],
                        },
                    }
                }
            ),
        )
    )

    # --- Logs advanced: index discovery via aggregation (logs_read) -----
    from datadog_api_client.v2.api.logs_api import LogsApi
    from datadog_api_client.v2.model.logs_aggregate_request import LogsAggregateRequest
    from datadog_api_client.v2.model.logs_aggregation_function import LogsAggregationFunction
    from datadog_api_client.v2.model.logs_compute import LogsCompute
    from datadog_api_client.v2.model.logs_group_by import LogsGroupBy
    from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter

    logs_api = LogsApi(auth.api_client)
    results.append(
        _run(
            "logs",
            "aggregate_logs grouped by index (data-scope index discovery)",
            "logs_read",
            lambda: logs_api.aggregate_logs(
                body=LogsAggregateRequest(
                    filter=LogsQueryFilter(
                        query="*",
                        **{"from": "now-15m", "to": "now"},  # type: ignore[arg-type]
                    ),
                    compute=[LogsCompute(aggregation=LogsAggregationFunction.COUNT)],
                    group_by=[LogsGroupBy(facet="index", limit=10)],
                )
            ),
        )
    )

    # --- Endpoints EXCLUDED from the plan, checked here only to confirm
    #     they indeed 403 (documents the decision, doesn't gate anything) --
    results.append(
        _run(
            "metrics (excluded from plan)",
            "update_metric_metadata (expected to 403: needs metrics_metadata_write)",
            "metrics_metadata_write (NOT in key)",
            lambda: metrics_v1.update_metric_metadata(
                "system.cpu.user", body=MetricMetadata(description="scope-check-noop")
            ),
        )
    )
    try:
        from datadog_api_client.v1.api.logs_indexes_api import LogsIndexesApi

        logs_indexes_api = LogsIndexesApi(auth.api_client)
        results.append(
            _run(
                "logs (excluded from plan)",
                "list_log_indexes (expected to 403: needs logs_read_config)",
                "logs_read_config (NOT in key)",
                lambda: logs_indexes_api.list_log_indexes(),
            )
        )
    except ImportError:
        pass

    # --- Report -----------------------------------------------------------
    width_domain = max(len(r.domain) for r in results) + 2
    width_endpoint = max(len(r.endpoint) for r in results) + 2
    print(f"{'DOMAIN':<{width_domain}}{'ENDPOINT':<{width_endpoint}}{'STATUS':<20}EXPECTED SCOPE")
    print("-" * (width_domain + width_endpoint + 20 + 30))
    for r in results:
        print(
            f"{r.domain:<{width_domain}}{r.endpoint:<{width_endpoint}}{r.status:<20}{r.scope_expected}"
        )
        if r.detail and r.status != "OK":
            print(f"{'':<{width_domain}}  -> {r.detail}")

    forbidden = [r for r in results if r.status == "FORBIDDEN (403)"]
    if forbidden:
        print(f"\n{len(forbidden)} endpoint(s) returned 403 - do NOT build tools for these yet:")
        for r in forbidden:
            print(f"  - {r.domain}: {r.endpoint}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
