# Step 7, part 3: Dashboard observability cards and charts

Verified on 2026-10-11.

## Delivered behavior

The Event Dashboard now has a Benchmark & Observability section with nine cards:
target EPS, acknowledged actual EPS, ingested events, average/p95/p99 query
latency, newest-event freshness, CPU, and memory. It also shows generated and
acknowledged totals, pending generated events, generator state, run ID, latency
sample count, browser observation count, and system sample timestamp.

Five charts cover actual EPS, three query-latency series, ingestion freshness,
CPU percentage, and memory percentage. Units are explicit and CPU/RAM axes span
0–100%. System series use the sampler's timestamps without duplicating cached
samples. Null measurements produce gaps/empty state and em dashes, not zeros.

Independent two-second polling reuses the serialized dashboard poller. A failed
request retains last-successful data and its update time, offers retry, and does
not stop business analytics. Navigation aborts requests and disposes polling and
charts. Browser history retains at most 300 observations within ten minutes and
resets on simulation ID changes, including transitions to or from no-run state.

Stopped/error runs identify their EPS as the final reported acknowledged rate
and explain that freshness grows after production stops. Resource scope and the
shared-client query-latency window are described in the UI. The two independently
polled sections identify their own run during brief run-transition differences.

## Verification

| Check | Result |
| --- | --- |
| Frontend production build | Passed |
| Frontend Vitest suite | 141 passed; 21 new tests |
| Selected Chromium browser suite | 12 passed; 4 new observability tests |
| Desktop / 390px mobile screenshots | Inspected; no horizontal overflow |
| Live benchmark endpoint + cards | Real CPU/RAM and latency rendered |
| v1 latest snapshot | Unchanged, event `2d084821-95f6-4ba5-956f-fc5952fd8f9e` |
| Backend and frontend deployment | Healthy |
| `git diff --check` | Passed |

Unit tests cover typed response validation, missing measurements, malformed
counts/rates, impossible percentages, timestamp bounds, backlog consistency,
300-point and ten-minute bounds, run resets, nulls, clock regression, detached
history, and transport cancellation.

Browser checks cover temporary and initial failures, retry and recovery,
business analytics continuing during observability failure, run-history reset,
unknown CPU/freshness, stopped-rate labels, slow requests without overlap,
navigation cancellation, real API data, and responsive layouts. The other eight
browser checks exercise existing v1 Settings/dashboard and v2 dashboard behavior.

Screenshots are generated under `frontend/test-results/observability-desktop.png`
and `frontend/test-results/observability-mobile.png`. Screenshot measurements are
controlled browser fixtures; a separate browser check uses the real API.

Both application services were restarted to activate the part 1/2 backend and
part 3 frontend. The previously stopped run's process-owned metadata was cleared
as documented; stored Kafka/Pinot events were preserved. No generator runs were
started and no events were published during this part's verification.

Controlled 50/100/250/500 EPS benchmarks and a conditional 1000 EPS scenario
remain part 4. This verification is not a throughput benchmark.
