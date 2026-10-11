# v2 phase 1: event data plane

Verified on 2026-10-11 against the running Apache Kafka 3.9.1 and Apache Pinot
1.5.1 services in the `ride-analytics` Compose project.

## Delivered

- Separate `ride-operations` topic: one partition and one replica.
- `operations` schema with column-based null handling, all event envelope fields,
  LONG sequence/time columns, and nullable user/driver/ride identifiers.
- Append-only `operations_REALTIME` ingestion using the JSON decoder and Kafka 3
  consumer, MMAP loading, simulation/type/zone inverted indexes, and timestamp
  range index. Segment flushing uses a one-hour interval and 100 MB target size.
- Independent, repeatable setup and a manual event ingestion smoke test.

The working JSON uses `ingestionConfig.streamIngestionConfig.streamConfigMaps`
rather than the legacy stream configuration location shown in the plan. The
Controller accepted it and realtime ingestion verified it on Pinot 1.5.1.

## Results

| Check | Result |
| --- | --- |
| Provisioning and smoke verification unit tests | All 9 tests passed, including existing v1 provisioning tests. |
| Topic creation | Created with one partition and one replica. |
| Schema/table registration | Controller accepted both; fetched resources matched committed configurations. |
| Repeatable provisioning | Existing matching schema/table recognized with no mutations. |
| Manual ingestion | 10 events appeared exactly once each; all stored fields matched. |
| Eight event types | Connected 1, waiting 2, disconnected 1; requested 2, cancelled 1, accepted 1, assigned 1, completed 1. |
| Optional IDs | Null user/driver/ride identifiers returned as null with query null handling enabled. |
| Ordering | All ten timestamps deliberately identical; sequence numbers 1–10 returned in order. |
| v1 preservation | Before/after comparison retained 16 snapshot rows and the identical latest snapshot. Existing dashboard API through the web proxy and Settings page returned successfully. |

The smoke simulation ID was `smoke-c642cd59-1014-413d-92bd-b66a2dd70956`.
Its events remain in v2 storage. The check published nothing to the v1 topic.

## Reproduce

```bash
bash scripts/setup-v2.sh
python3 -m unittest discover -s infra/pinot -p 'test_*.py'
python3 infra/pinot/smoke_test_operations.py
```

Setup is idempotent and inserts no data. The smoke command appends ten events
under a fresh simulation ID on every run. It validates a cancelled request and a
separate accepted/completed ride, followed by driver disconnection. These manual
fixtures establish the data plane; the reusable simulation engine belongs to
phase 2. No generator, v2 API, or v2 dashboard is implemented in this phase.
