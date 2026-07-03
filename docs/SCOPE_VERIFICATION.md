# Scope verification (Fase 2 of the revamp)

This records the scope research behind which new tools were built in this
revamp, and how to confirm it against the team's real app key.

## Why this exists

The team's app key is exclusive to this MCP server and only has:

- Read: `logs_read`, `metrics_read`, `dashboards_read`, `monitors_read`, `apm_read`
- Write: `metrics_write`, `dashboards_write`, `monitors_write`, `monitors_downtime_write`

An earlier draft of this plan assumed two endpoints were covered by those
scopes without checking; they are not. This document exists so that mistake
doesn't repeat: every new endpoint below has a documented scope rationale,
and `scripts/verify_scopes.py` lets the team confirm it empirically against
the real key with read-only/no-side-effect calls before relying on it in
production.

## How to run the live check

```bash
export DD_API_KEY=...   # the team's real key
export DD_APP_KEY=...
uv run python scripts/verify_scopes.py
```

This was **not run against a live key while writing this revamp** - no
Datadog credentials were available in the development environment. The
table below reflects research against Datadog's official RBAC permissions
reference (`docs.datadoghq.com/account_management/rbac/permissions`) and the
`datadog-api-client` 2.57.0 source. Treat it as "high confidence, pending
live confirmation" rather than a guarantee - run the script once before
depending on these tools for anything important, and rerun it after this PR
merges.

## Bugfix discovered during the client bump: `get_full_trace`

The pre-existing `get_full_trace` tool imported
`datadog_api_client.v2.api.traces_api.TracesApi`, which **does not exist**
in `datadog-api-client` 2.57 (confirmed: `ModuleNotFoundError` at import
time - this tool would have crashed on every call). The client's real v2
per-trace endpoint is `apm_trace_api.APMTraceApi.get_trace_by_id`, a
purpose-built "get one trace by ID" call - strictly better than the old
code's workaround of searching spans by a `trace_id:` filter query. Fixed
as part of this revamp's APM migration; same `apm_read` scope as the rest
of the APM domain (Datadog groups all APM data-read endpoints, including
trace detail, under this single permission).

## Endpoints included in this revamp

| Domain | Endpoint (`datadog-api-client` method) | Scope used | Confidence | Notes |
|---|---|---|---|---|
| Downtimes | `v2.DowntimesApi.list_downtimes` / `get_downtime` | `monitors_downtime_write` | High | Datadog RBAC has a single `monitors_downtime` ("Manage Downtimes") permission covering the whole downtime feature (list, create, update, cancel) - there is no separate read-only downtime permission in the RBAC/scopes model, so a key with downtime write access should also be able to list/get. |
| Downtimes | `v2.DowntimesApi.create_downtime` / `update_downtime` | `monitors_downtime_write` | High | Same permission as above; this is the scope's primary purpose. |
| Monitors | `v1.MonitorsApi.search_monitors` | `monitors_read` | High | Same permission family as `list_monitors`, which the server already uses successfully. |
| Monitors | `v1.MonitorsApi.validate_monitor` | `monitors_write` | High | Validates monitor syntax without creating anything (confirmed via the client's own docstring). One caveat: Datadog's docstring notes log-type monitor validation additionally needs an unscoped app key + `logs_read_data`; document this in the tool so agents get a clear error instead of a silent failure for that one case. |
| Metrics | `v1.MetricsApi.list_active_metrics` | `metrics_read` | High | Same API class/permission as `list_metrics`, already in use. |
| Metrics | `v1.MetricsApi.get_metric_metadata` | `metrics_read` | High | Read-only sibling of `update_metric_metadata` (excluded, see below). |
| Metrics | `v2.MetricsApi.list_tags_by_metric_name` | `metrics_read` | Medium-High | Distinct API class (`v2.MetricsApi`, tag configuration) from `v1.MetricsApi`; Datadog docs group it under the same "Metrics" read scope but this is the one metrics endpoint worth double-checking live. |
| APM | `v2.SpansApi.aggregate_spans` | `apm_read` | High | Same API class as `list_spans` (already in use for `search_apm_traces`), just a different operation. |
| Logs | `v2.LogsApi.aggregate_logs` grouped by `index` | `logs_read` | High | Identical permission and API class to `count_logs`/`aggregate_logs_by_field`, which already work; only the `group_by` facet changes. |

## Endpoints explicitly excluded (would 403)

| Domain | Endpoint | Scope required | Why excluded |
|---|---|---|---|
| Metrics | `v1.MetricsApi.update_metric_metadata` | `metrics_metadata_write` | Datadog RBAC lists "Metrics Metadata Write" as a permission distinct from `metrics_write`. The key does not have it. |
| Logs | `v1.LogsIndexesApi.list_log_indexes` | `logs_read_config` | This is a log **configuration** endpoint (same API class as `create_logs_index`/`delete_logs_index`), gated by `logs_read_config`, not the log **data** scope `logs_read` the key has. Index discovery is done instead via `aggregate_logs_by_field`/`describe_metric`-style grouping by the `index` facet, which only needs `logs_read`. |

If the team later widens the app key's scopes, both exclusions can be
revisited - `scripts/verify_scopes.py` includes checks for them (expected to
report `FORBIDDEN (403)` today) so re-running it after a scope change will
show when they become available.

## Domains deferred entirely (out of scope for this revamp)

Events, SLOs, Incidents, Hosts, Synthetics, RUM, Security Monitoring,
Notebooks, and Service Catalog all require scopes the key does not have
(e.g. `events_read`, `slos_read`, `incident_read`, `hosts_read`,
`synthetics_read`, `rum_read`, `security_monitoring_signals_read`). They are
not implemented. If the key's scopes are ever widened, `scripts/verify_scopes.py`
can be extended with checks for these domains before building tools for them.
