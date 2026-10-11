# v2 phase 3: scheduling, publication, and lifecycle

Verified on 2026-10-11 using Python 3.13, Kafka 3.9.1, and Pinot 1.5.1.

## Delivered

- 100 ms event-budget scheduler, fractional credit accounting, one/two-event
  action costs, bounded budgets, and normal-event driver warm-up.
- Separate ordered operations producer with all-replica acknowledgements,
  idempotence, 5 ms linger, enqueue-then-await batching, and bounded drain.
- Single-process lifecycle service: STOPPED, WARMING_UP, RUNNING, STOPPING,
  plus ERROR for failures that cannot safely be reported as successful stops.
- Fresh immutable run metadata, conflict protection, serialized controls,
  graceful stopping, caller-cancellation protection, and retained diagnostics.
- FastAPI lifecycle ownership with lazy producer startup and generator shutdown
  before v1 client cleanup. No generator HTTP endpoints or UI in this phase.
- Finite live verification command and periodic summary logs.

## Automated results

All **164 backend tests passed**, including **30 new scheduler/service/producer
tests**. The existing Starlette TestClient deprecation warning remains.

Tests cover preset/custom rates and low fractional rates, positive integer
validation, warm-up transitions, exact event costs, frozen run metadata,
fresh restart, concurrent Start conflicts, waiting for in-flight sends,
Stop cancellation, idle/repeated Stop, publication/drain/startup failures,
bounded cleanup, no application replay, preserved delivery futures, slow-broker
backpressure, measured rate within 10%, and application shutdown ordering.
All existing domain invariant and v1 backend tests continue to pass.

## Live results

| Run | Duration | Target EPS | Final measured acknowledged EPS | Generated / acknowledged / Pinot rows |
| --- | --- | --- | --- | --- |
| `sim-ddc0ab48-fc05-44fb-a1f6-25dcfc2007a0` | 10 seconds | 250 | 245.45 | 2,500 / 2,500 / 2,500 |
| `sim-1440a294-9670-4c6b-baa4-78a9826e4fc8` | 2 seconds | 250 | 249.85 | 500 / 500 / 500 |

Both runs ended STOPPED with no error. Each had all eight event types, unique
event IDs, sequences from 1 through its event count, fresh pools, and a distinct
simulation ID. After ingestion settled, a raw-event projection of latest driver
and ride events matched generator waiting drivers, assigned drivers, and active
users. Final statistics stayed unchanged after Stop. The v1 snapshot count was
identical before and after the live test.

The normal backend was updated afterward and passed its health check. A second
before/after comparison confirmed all 16 v1 rows and the complete latest snapshot
were unchanged, and the dashboard API responded through the frontend proxy.

The test appended 3,000 events to `operations_REALTIME` and did not delete prior
runs. These short correctness/rate checks do not replace phase 7's sustained
load and resource benchmarks.

## Reproduce

```bash
bash scripts/setup-v2.sh
docker compose --profile api build backend
docker compose --profile api run --rm --no-deps backend python -m pytest -q
docker compose --profile api run --rm --no-deps backend python scripts/verify-generator.py
```

Only the live command publishes events. It runs in a disposable backend
container on the existing Compose network, uses fresh simulation IDs, and leaves
the normal application's generator stopped. The generator service is in memory:
process restart loses runtime diagnostics; stored Kafka/Pinot events remain.

Kafka acknowledgements and Pinot ingestion are separate observations. Paired
business events are ordered but not transactional. An uncertain delivery ends
the run in ERROR; never reuse that run's advanced state for further generation.
