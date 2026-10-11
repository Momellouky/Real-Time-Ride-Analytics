# v2 phase 5: Pinot analytical queries

Verified on 2026-10-11 against Apache Pinot 1.5.1 and Kafka 3.9.1.

## Delivered

- Validated run-scoped SQL for recent ride counts, one-hour minute aggregates,
  latest driver states, active users, observed users, and ten-minute event rate.
- Multi-stage and null-handling query options in the shared client, with unchanged
  default v1 request behavior and additional truncation checks.
- Concurrent six-query service with a shared time cutoff, typed aggregate
  responses, explicit failures, zeros for missing categories, and sparse series.
- Known-sequence integration script and automated unit coverage.

The combined dashboard endpoint, run metadata integration, and Vue analytics
dashboard remain phase 6 work. This phase does not replace generator diagnostics
with snapshots or fetch raw events for application-side analytical computation.

## Version compatibility

The installed Broker rejected `ARG_MAX(event_timestamp, sequence_number,
event_type)` with the plan's alias in single-stage mode and rejected the function
signature in multi-stage mode. `LASTWITHTIME(event_type, sequence_number,
'STRING')` worked in multi-stage subqueries and grouped outer queries.

This ordering is valid for generator runs because sequences strictly increase
and timestamps never regress. It handles the equal-timestamp connected/waiting,
accepted/assigned, and completed/waiting transitions. Externally imported records
must satisfy those run invariants. Query options, rather than cluster configuration
changes, enabled the required engine/null semantics on the existing deployment.

## Automated results

All **229 backend tests passed**, including **38 new analytical query/client
cases**. Existing v1 APIs, generator controls, and domain tests continue to pass.
The existing upstream Starlette TestClient warning remains.

Coverage includes all query filters/windows, unsafe identifier rejection before
I/O, null-aware distinct/latest queries, empty-run mapping, sorted/aligned
buckets, timestamp range validation, unknown/duplicate groups, malformed counts,
incorrect/nonfinite rates, scalar response errors, query failure propagation,
per-query options, and partial/truncated result rejection.

## Live results

The fixture script ingested 21 events across:

- `analytics-bcbf832b-41f6-4292-ac6d-de408fd74238`: 20 events.
- `analytics-ea09ad73-b607-4bb9-9272-7baafab42d26`: 1 event using overlapping
  entity IDs to verify run isolation.

The first run contained eight old events (65 minutes earlier), ten recent events
(30 seconds earlier), and two future transitions. Fixed-cutoff analytics returned:

| Observation | Expected and observed |
| --- | --- |
| Last-minute ride counts | Requested 3, accepted 1, cancelled 1, completed 1. |
| Current driver states | Waiting 1, assigned 1, disconnected 1; online 2, observed 3. |
| Active/observed users | Active 2, observed 3. |
| Hourly lifecycle history | One minute bucket containing the recent lifecycle counts; old/future events excluded. |
| Ingested rate | One ten-second bucket with 10 events, yielding 1.0 EPS. |
| Timestamp ties | Final driver/user states selected by sequence within equal timestamps. |
| Long-lived state | The old accepted ride and assigned driver remained active/current. |
| Future state | Future cancellation/disconnection did not alter current counts at the cutoff. |
| Other run | One requested/active/observed user, no online drivers; first-run counts unaffected. |
| Unknown run | Zero scalar/group counts and empty series. |
| Normal run reconciliation | Pinot waiting/assigned drivers and active users matched the stopped application generator. |
| v1 preservation | Live script confirmed its snapshot row count was unchanged. |
| Final application check | All 16 v1 rows and the latest snapshot remained unchanged; the generator retained its stopped run ID and final diagnostics. |

The six concurrent queries for the main fixture completed in **147 ms**. This is
a small correctness fixture measurement, not a sustained performance benchmark.
The initial script attempt failed on a reserved SQL alias before publishing any
events; the corrected successful run added exactly 21 events.

## Semantics and limits

Latest-state queries cover the whole run with an upper cutoff. Windowed event
counts include their lower/upper bounds. Multiple analytical queries can observe
different realtime ingestion progress despite sharing a cutoff. Sparse time
series report observed buckets; edge buckets can be partial. Rate always divides
by ten seconds, as specified in the plan.

No configured-pool totals are inferred from observed events. Never-connected
drivers have no record, so complete offline counts require run metadata in phase
6. Aggregate group/query limits are surfaced as errors. No fallback converts a
failed query into an empty dashboard.

## Reproduce

```bash
bash scripts/start.sh
docker compose --profile api run --rm --no-deps backend python -m pytest -q
docker compose --profile api run --rm --no-deps backend python scripts/verify-operations-analytics.py
```

Each live invocation appends 21 isolated events. Stored prior runs and application
generator state are preserved. The v2 dashboard API/UI will expose these verified
aggregates in the next phase.
