# v2 phase 4: Generator API and UI

Verified on 2026-10-11 with the existing Kafka/Pinot infrastructure and Chromium.

## Delivered

- Typed Start/Stop/Status endpoints under `/api/v2/generator`, strict complete
  configuration validation, conflict handling, and generator-specific errors.
- `/generator` page and navigation link with default pools, five rate presets,
  custom rate input, and non-blocking warnings above 1,000 events/sec.
- One-second status polling, serialized commands, stale-response protection,
  polling cancellation on navigation, retry, and control-error reconciliation.
- Simulation identity, rates, generated/acknowledged events, pool sizes, runtime
  state, failure details, and six population diagnostics.
- Responsive desktop/mobile layout and retained stopped-run statistics.
- Standard startup now also creates/checks v2 resources without publishing data;
  full verification ensures those resources exist before browser tests.

## Results

| Verification | Result |
| --- | --- |
| Backend suite | 191 passed, including 27 new Generator API cases. |
| Frontend suite | 105 passed, including 32 Generator domain/store cases and a v2 HTTP transport case. |
| Final Chromium run | 11 passed: 5 Generator scenarios and 6 existing v1 error/empty/validation scenarios. |
| Live controls | UI Start returned 202; duplicate Start conflicts are covered by API tests. Stop completed with generated = acknowledged events. Restart created a different simulation ID. |
| Status polling | Displayed event count advanced without a page refresh. Reload/navigation reconnected to the same active run. Leaving the page stopped polling without stopping the generator. |
| Validation | Zero/fractional/blank fields blocked Start; custom 1,250 EPS showed a warning and remained allowed. API rejected unsupported fields and non-integer inputs. |
| Error recovery | Unavailable status retried successfully; Start failures preserved edits; conflict responses reconciled an existing run; STOPPING disabled controls; ERROR retained diagnostics. |
| Pinot ingestion | Both UI-created runs had exact total and distinct event counts matching acknowledged publication. |
| Responsive layout | Desktop/mobile screenshots captured; mobile page had no horizontal overflow. |
| v1 preservation | Final comparison retained all 16 rows and the identical complete latest snapshot. |
| Startup resources | Repeated topic and table provisioning recognized matching existing resources without replacing them. |

Final live runs used 30 users, 5 drivers, and 50 events/sec:

- `sim-050e61a7-5761-4eee-9b8c-b4852ae4644c`: 60 generated,
  60 acknowledged, 60 distinct Pinot rows; final measured rate 50.31 EPS.
- `sim-0c4dd63d-ddf9-4c95-b0f2-40fb72370e88`: 10 generated,
  10 acknowledged, 10 distinct Pinot rows. This immediate-restart check was too
  short for a steady-state throughput measurement.

An earlier browser pass appended 25 events across two separate runs. Total
verification writes in this phase were 95 v2 events; no v1 snapshots were
published. The application generator was stopped at test completion.
Browser screenshots are in `frontend/test-results/generator-desktop.png` and
`generator-mobile.png`. The backend suite retains its upstream TestClient warning.

## Reproduce

```bash
bash scripts/start.sh
docker compose --profile api run --rm --no-deps backend python -m pytest -q
docker compose --profile test build frontend-test
docker compose --profile test run --rm --no-deps frontend-test
docker compose --profile web --profile e2e build frontend-e2e
docker compose --profile web --profile e2e run --rm --no-deps frontend-e2e \
  npm run test:e2e -- generator.spec.js
```

Run browser verification with the generator stopped. Live tests append immutable
v2 runs, while unit tests and intercepted browser scenarios publish nothing.
Analytical v2 dashboard endpoints and charts remain for phases 5 and 6.
