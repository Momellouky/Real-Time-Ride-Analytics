# Step 7, part 2: Combined benchmark API

Verified on 2026-10-11.

## Delivered

`GET /api/v2/benchmark/metrics` has a typed response combining generator status,
target and acknowledged actual EPS, generated/published counts, Pinot-visible
row count, newest-event age, query latency, and cached system measurements.

One COUNT/MAX aggregate uses the captured simulation ID, zone, and timestamp
cutoff. Combining the two aggregates avoids separate count/freshness queries
observing different ingestion progress. Generator counters are sampled after
query I/O; changing runs during that I/O returns 409.

No-run state skips Pinot and returns zero counts with null freshness. An empty
run also returns null freshness, verified against real Pinot with SQL null
handling enabled. Stopped runs remain available; their newest-event age grows
naturally. This is application freshness, not Kafka consumer-group lag.

Pinot errors and invalid aggregates return 503. Pending generated events are
clamped to zero. Shared latency includes the endpoint's own query and other
queries, including v1, over the latest 500 samples. Missing system samples and
initial CPU priming are explicitly nullable. The benchmark UI remains part 3.

## Checks

| Check | Result |
| --- | --- |
| Backend image build | Passed |
| Full backend pytest suite | 295 passed; 29 new endpoint/query cases |
| Real endpoint with existing stopped run | 35,010 ingested = 35,010 published |
| Empty-run COUNT/MAX query | Zero count, null timestamp and freshness |
| No-run endpoint | No additional Pinot query |
| `git diff --check` | Passed |

The endpoint tests cover composition, cached system samples, shared latency,
all lifecycle states, run-filtered queries, no-run and empty-run responses,
nonnegative backlog, clock regression, counters changing during query execution,
run changes, failures, malformed/negative/future aggregates, and unsafe SQL IDs.

The read-only integration verifier uses real Pinot and system sampling, while
injecting the existing application's generator metadata/runtime snapshot into a
temporary FastAPI instance. It starts no generator runs, publishes no events,
and leaves the running application and its current run metadata intact.
The stopped run verified was `sim-a0b0c08b-4b7b-4cb2-91be-c15e02f62bd7`.
Its pending count was zero. One query took 12.71 ms; freshness was 712,021 ms,
reflecting the age of the stopped run rather than ingestion backlog. These are
point-in-time verification observations, not benchmark results.

Reproduce the integration check after ingestion catch-up:

```bash
docker compose --profile api run --build --rm --no-deps backend \
  python scripts/verify-benchmark-api.py
```

The backend image is built. Running services were not restarted to preserve run
metadata; the endpoint becomes available on the next backend restart. The
existing Starlette/httpx test-client deprecation warning remains.
