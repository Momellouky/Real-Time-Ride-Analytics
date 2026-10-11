"""Known-sequence integration checks for v2 SQL. Appends isolated fixture runs."""
import asyncio
import json
import time
from uuid import uuid4

import httpx

from app.config import Settings
from app.generator.events import EventType, OperationEvent
from app.services.kafka_producer import OperationsKafkaProducer
from app.services.operations_analytics import OperationsAnalytics
from app.services.pinot_client import PinotClient


def fixtures(simulation_id, now):
    old, recent, future = now - 65 * 60_000, now - 30_000, now + 60_000
    specs = [
        (old, 'DRIVER_CONNECTED', None, 'd1', None),
        (old, 'DRIVER_WAITING', None, 'd1', None),
        (old, 'RIDE_REQUESTED', 'u1', None, 'r1'),
        (old, 'RIDE_ACCEPTED', 'u1', 'd1', 'r1'),
        (old, 'DRIVER_ASSIGNED', 'u1', 'd1', 'r1'),
        (old, 'DRIVER_CONNECTED', None, 'd3', None),
        (old, 'DRIVER_WAITING', None, 'd3', None),
        (old, 'DRIVER_DISCONNECTED', None, 'd3', None),
        (recent, 'DRIVER_CONNECTED', None, 'd2', None),
        (recent, 'DRIVER_WAITING', None, 'd2', None),
        (recent, 'RIDE_REQUESTED', 'u2', None, 'r2'),
        (recent, 'RIDE_CANCELLED', 'u2', None, 'r2'),
        (recent, 'RIDE_REQUESTED', 'u2', None, 'r3'),
        (recent, 'RIDE_ACCEPTED', 'u2', 'd2', 'r3'),
        (recent, 'DRIVER_ASSIGNED', 'u2', 'd2', 'r3'),
        (recent, 'RIDE_COMPLETED', 'u2', 'd2', 'r3'),
        (recent, 'DRIVER_WAITING', None, 'd2', 'r3'),
        (recent, 'RIDE_REQUESTED', 'u3', None, 'r4'),
        (future, 'RIDE_CANCELLED', 'u3', None, 'r4'),
        (future, 'DRIVER_DISCONNECTED', None, 'd2', None),
    ]
    return [OperationEvent(str(uuid4()), simulation_id, i, stamp, EventType(kind), user, driver, ride)
            for i, (stamp, kind, user, driver, ride) in enumerate(specs, 1)]


async def main():
    settings = Settings()
    now = time.time_ns() // 1_000_000
    run = 'analytics-' + str(uuid4())
    other = 'analytics-' + str(uuid4())
    events = fixtures(run, now)
    other_events = [OperationEvent(str(uuid4()), other, 1, now - 30_000, EventType.RIDE_REQUESTED, 'u1', ride_id='r1')]
    producer = OperationsKafkaProducer(settings.kafka_bootstrap_servers, settings.kafka_publish_timeout_seconds)
    pinot = PinotClient(str(settings.pinot_broker_url), timeout=20)
    analytics = OperationsAnalytics(pinot)
    try:
        before = await pinot.query('SELECT COUNT(*) AS snapshot_count FROM ride_metrics')
        await producer.start()
        await producer.publish_batch(events + other_events)
        await producer.stop()
        async with asyncio.timeout(120):
            while True:
                count = await pinot.query(f"SELECT COUNT(*) AS count FROM operations WHERE simulation_id IN ('{run}','{other}')")
                if count == [{'count': 21}]:
                    break
                await asyncio.sleep(1)
        started = time.monotonic()
        result = await analytics.read(run, as_of_ms=now)
        elapsed = time.monotonic() - started
        assert result.recent_rides.model_dump() == dict(requested=3, accepted=1, cancelled=1, completed=1), result
        assert result.drivers.waiting == 1 and result.drivers.assigned == 1 and result.drivers.disconnected == 1, result
        assert result.drivers.online == 2 and result.drivers.observed == 3, result
        assert result.active_users == 2 and result.observed_users == 3, result
        assert len(result.ride_history) == 1, result
        assert result.ride_history[0].time_bucket == (now - 30_000) // 60_000 * 60_000
        assert result.ride_history[0].requested == 3 and result.ride_history[0].completed == 1
        assert len(result.event_rate) == 1 and result.event_rate[0].event_count == 10, result
        assert result.event_rate[0].events_per_second == 1.0, result
        isolated = await analytics.read(other, as_of_ms=now)
        assert isolated.active_users == isolated.observed_users == isolated.recent_rides.requested == 1
        assert isolated.drivers.online == 0
        empty = await analytics.read('analytics-' + str(uuid4()), as_of_ms=now)
        assert empty.observed_users == empty.active_users == empty.drivers.online == 0
        assert not empty.ride_history and not empty.event_rate
        # Reconcile a normal service run against genuine Pinot aggregates.
        async with httpx.AsyncClient(timeout=20) as client:
            status = (await client.get('http://backend:8000/api/v2/generator/status')).json()
        if status['simulation_id'] and status['status'] == 'STOPPED':
            normal = await analytics.read(status['simulation_id'])
            assert normal.drivers.waiting == status['in_memory']['waiting_drivers']
            assert normal.drivers.assigned == status['in_memory']['assigned_drivers']
            assert normal.active_users == status['in_memory']['waiting_users'] + status['in_memory']['users_in_ride']
        assert await pinot.query('SELECT COUNT(*) AS snapshot_count FROM ride_metrics') == before
        print('PASS: latest-state ties, old active state, windows, future exclusion, null IDs, run isolation, empty state, and reconciliation.')
        print(json.dumps({'fixture_run': run, 'other_run': other, 'events_added': 21,
                          'six_query_elapsed_seconds': round(elapsed, 3), 'result': result.model_dump()}, indent=2))
    finally:
        await producer.stop()
        await pinot.close()


if __name__ == '__main__':
    asyncio.run(main())
