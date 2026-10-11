# Step 6: Combined dashboard API and v2 dashboard UI

Verified on 2026-10-11 against the running Kafka/Pinot stack.

## Delivered behavior

- `GET /api/v2/dashboard` combines immutable current/last run metadata with the
  six Pinot analytical queries from step 5, using a shared timestamp cutoff.
- Eight cards cover the configured user pool, active users, online/waiting
  drivers, and four ride lifecycle event counts in the last 60 seconds.
- `/dashboard-v2` provides four per-minute ride series over an hour, per-10-second
  ingested event rate over ten minutes, and a driver distribution with explicit
  connected/waiting/assigned/offline states. Offline includes unobserved drivers.
- Serialized polling, cancellation on navigation, automatic recovery, manual
  retry, and last-successful-data retention reuse the existing dashboard poller.
- Initial state is empty without Pinot queries. Stopped runs retain metadata and
  latest state while time windows expire. New runs replace the entire response.
  A concurrent run change returns 409 rather than mixing metadata and analytics.
- Query failures and impossible population totals return 503 without a fallback
  to generator in-memory diagnostics. Backend restarts clear run metadata while
  retaining Kafka/Pinot data.

## Verification

| Check | Result |
| --- | --- |
| Backend pytest suite | 241 passed |
| Frontend Vitest suite | 120 passed |
| Selected Chromium browser tests | 9 passed |
| Frontend production build | Passed |
| Desktop and 390px mobile screenshots | Inspected; no horizontal overflow |
| v1 latest snapshot | Unchanged, event `2d084821-95f6-4ba5-956f-fc5952fd8f9e` |
| v1 Pinot row count | 16 |
| Generator after verification | STOPPED |
| `git diff --check` | Passed |

Backend tests include no-run behavior, every lifecycle state, stopped-run
retention, metadata-to-analytics composition, offline unobserved drivers,
population bounds, query failures, and a run change during awaited queries.
Frontend tests validate counts, state totals, ordered/bounded buckets, and rates.

The browser suite includes three new v2 tests and six existing v1 tests. It
checks recovery after 503, complete run replacement, navigation cancellation,
empty state, mobile layout, and real Start → Kafka → Pinot → dashboard → Stop.
For a stopped second run, all acknowledged events were ingested and Pinot's
active-user, waiting-driver, and online-driver counts matched generator
in-memory diagnostics. Diagnostics are used only as verification evidence.

The live test was run twice, creating four short runs with fresh IDs and leaving
the final run stopped. No v1 snapshots were published. Screenshots are written to
`frontend/test-results/dashboard-v2-desktop.png` and
`frontend/test-results/dashboard-v2-mobile.png` (ignored generated artifacts).

The backend suite emits the existing Starlette/httpx deprecation warning.
Benchmarking and tuning at the plan's target rates remain step 7.
