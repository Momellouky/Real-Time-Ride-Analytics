# Acceptance verification

The PRD and implementation plan define a complete snapshot workflow for `ZONE_1`.
This document maps the requirements to reproducible checks and records the final
verification results.

## Coverage

| Requirement | Evidence |
| --- | --- |
| Documented startup | `scripts/start.sh`; clean Compose project with fresh volumes and alternate ports. |
| Five Settings inputs and submit button | Chromium Settings tests. |
| Non-negative integer input | Backend validation tests, frontend validation tests, and browser input rejection. |
| Accepted + cancelled ≤ requests | Backend model/API tests and browser validation. |
| Waiting ≤ online drivers | Backend model/API tests and browser validation. |
| Complete event with no null metric | API tests and live Kafka consumer in `backend/scripts/smoke-test.py`. |
| One snapshot per successful submission | Producer/API tests and event-ID row count in the live smoke test. |
| Kafka → Pinot REALTIME ingestion | Manual ingestion smoke test and API ingestion smoke test. |
| Five current values and history charts | Dashboard Chromium test; desktop and mobile screenshots. |
| Polling updates without browser refresh | Dashboard and Settings open in separate browser tabs during live submission. |
| Settings reloads persisted values | Settings Chromium live test. |
| Empty table yields zero state | Backend tests, fresh-stack API checks, and browser zero-state tests. |
| Last-hour history only | SQL lower/upper bounds and live old/recent/future observation check. |
| One zone included in event and API | Request/response models and unsupported-zone tests. |
| No transactional database or authentication | Compose services and application architecture review. |
| Query/publication failures are visible | Backend HTTP 503 tests, frontend API tests, and browser retry/recovery scenarios. |
| No overlapping polling and cleanup on navigation | Frontend timer/cancellation tests and Chromium navigation check. |
| Data survives restarts | Fresh verification project stopped and restarted without deleting volumes; event count and current snapshot compared. |

## Reproduce

```bash
bash scripts/start.sh
bash scripts/verify.sh
```

Live verification adds snapshots. To check a separate stack, use a new terminal
and alternate ports:

```bash
export COMPOSE_PROJECT_NAME=ride-analytics-check
export KAFKA_PORT=19092 PINOT_CONTROLLER_PORT=19000 PINOT_BROKER_PORT=18099
export BACKEND_PORT=18000 FRONTEND_PORT=15173
bash scripts/start.sh
bash scripts/verify.sh
```

Run `docker compose --profile web down` from that terminal afterward. Named volumes
remain available for a later restart. Avoid reusing a verification project name
when a truly empty-table check is required.

Browser artifacts are written to `frontend/test-results/`. API health is process
health; the live smoke tests establish working Kafka publication and Pinot reads.
The browser zero-state and error scenarios use intercepted responses; fresh-stack
API checks additionally verify empty-table behavior against real Pinot.

## Final results

Verified on 2026-10-11 using the separate `ride-analytics-validation` Compose
project and the alternate ports above.

| Check | Result |
| --- | --- |
| Provisioning tests | 4 passed. |
| Backend tests | 98 passed. |
| Frontend unit tests | 72 passed. |
| Chromium end-to-end tests | 8 passed. |
| Backend dependency consistency | `pip check` passed. |
| Fresh startup | All seven services healthy; real dashboard API returned five zeros, null event metadata, and empty history before publishing. |
| Live ingestion | Manual Kafka event and API submission each appeared exactly once in Pinot; invalid submissions emitted no Kafka event. |
| Browser integration | Settings submissions persisted and updated all dashboard cards/charts without reloading. |
| Restart persistence | Stopped the entire validation project without deleting volumes, restarted with `scripts/start.sh`, and confirmed all four rows and the complete latest snapshot were unchanged. |
| History boundaries | Published three dedicated fixtures: 65 minutes old, 30 seconds old, and 5 minutes in the future. All three ingested; only the recent fixture appeared in history, which remained ordered and inside the last-hour window. Current correctly selected the newest timestamp. |
| Repeatable provisioning | Restart recognized matching schema/table and made no changes to them. |

The boundary fixtures were published only to the validation project after the
normal suite and persistence checks. The suite added four snapshots and the
boundary check added three more. The validation stack was then stopped with its
volumes retained. No verification snapshots were published to the main project.

The backend suite reports one upstream Starlette TestClient deprecation warning;
it does not affect these results. Desktop and mobile browser screenshots are
available in `frontend/test-results/`.
