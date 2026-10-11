# v2 phase 2: simulation model

Verified on 2026-10-11 using the backend Docker image and Python 3.13.

## Delivered

- User, driver, and ride entities with the state machines from the v2 plan.
- Fresh run identity, fixed `ZONE_1`, validated positive integer populations,
  per-run event sequence, unique ride IDs within each run, and UUID event IDs.
- Indexed state pools and constant-time random candidate selection.
- Six valid business actions with one- or two-event transition costs.
- Weighted action selection that excludes unavailable actions and optionally
  respects an event budget. This is selection logic, not a running rate limiter.
- Immutable event envelopes, JSON serialization, and non-regressing timestamps.
- Runtime diagnostics and a full index/relationship invariant audit.

Only active rides remain in simulation memory. Completed/cancelled ride objects
leave active storage after their terminal events are created. The returned events
carry the history for phase 3's publisher. The model retains neither an event log
nor an ever-growing collection of terminal rides.

## Results

The complete backend suite passed: **134 tests**, including **36 new simulation
tests**. It reports the existing upstream Starlette TestClient deprecation warning.

| Requirement | Evidence |
| --- | --- |
| Fresh users/drivers and simulation identity | Defaults, separate-run isolation, UUID identity, and strict pool-size tests. |
| One active ride per user | Requests rejected for both waiting and in-ride users. |
| Cancellation before acceptance only | Requested cancellation restores IDLE; accepted cancellation leaves state unchanged. |
| Acceptance requires a requested ride and waiting driver | Offline/assigned driver and already-accepted ride rejection tests. |
| One ride per assigned driver | A second acceptance is rejected until the first ride completes. |
| Assigned drivers cannot disconnect | Explicit no-event/no-mutation test. |
| Completion restores IDLE/WAITING | Full lifecycle checks both states and removes reciprocal active-ride references. |
| Terminal transitions cannot repeat | Completion/cancellation retries emit nothing. |
| Complete event envelopes and paired sequence ordering | Exact event types/IDs/links, JSON fields, null IDs, UUIDs, and sequences verified. |
| High-rate timestamp ties | Fixed clock produces equal timestamps with strictly increasing sequence numbers. Clock regression test preserves latest-state ordering. |
| Valid weighted selection and event costs | Preconditions, plan weights, insufficient budgets, and selected action event counts checked. |
| State indexes remain consistent | Swap-removal and duplicate protection tested; full audits after randomized actions. |
| Independent event reconstruction | Five seeded runs of 2,000 actions each replay events through a separate state projection and compare users, drivers, active links, and rides after every action. All eight event types occur in each run. |
| Bounded active memory | 1,000 completed rides with a one-user/one-driver pool leave no terminal ride accumulation; random runs also stay within user-pool size. |
| Audit detects corruption | An intentionally broken driver-to-ride reference fails the invariant audit. |
| Existing backend behavior | All previous 98 backend tests remain passing. |

## Reproduce

```bash
docker compose --profile api build backend
docker compose --profile api run --rm --no-deps backend python -m pytest -q
```

No Kafka events were published by these tests. The running v1 application and
v2 data-plane resources were not restarted or changed. There are no generator
routes, UI controls, background scheduling, or Kafka publishing in this phase.
