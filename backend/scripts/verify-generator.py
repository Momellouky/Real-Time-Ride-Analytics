"""Finite live generator check. Adds two v2 runs; never writes to v1."""
import asyncio
import json

import httpx

from app.config import Settings
from app.generator.events import EventType
from app.generator.service import GeneratorService


async def query(client, settings, sql):
    response = await client.post(str(settings.pinot_broker_url).rstrip('/') + '/query/sql',
                                 json={'sql': sql, 'queryOptions': 'enableNullHandling=true'})
    response.raise_for_status()
    data = response.json()
    assert not data.get('exceptions'), data
    assert data.get('numServersResponded', 0) > 0, data
    assert data['numServersResponded'] == data['numServersQueried'], data
    table = data['resultTable']
    return [dict(zip(table['dataSchema']['columnNames'], row, strict=True)) for row in table['rows']]


async def main():
    settings = Settings()
    service = GeneratorService(settings.kafka_bootstrap_servers, settings.kafka_publish_timeout_seconds)
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        before = await query(client, settings, 'SELECT COUNT(*) AS snapshots FROM ride_metrics')
        for duration, users, drivers in [(10, 100, 20), (2, 30, 5)]:
            started = await service.start(users, drivers, 250, seed=2026)
            assert started['generated_events'] == started['published_events'] == 0
            try:
                await asyncio.sleep(duration)
            finally:
                final = await service.stop()
            assert final['status'] == 'STOPPED' and final['last_error'] is None, final
            assert final['generated_events'] == final['published_events'], final
            assert 225 <= final['actual_events_per_second'] <= 275, final
            service.simulation.check_invariants()
            expected = final['published_events']
            sql = ("SELECT * FROM operations WHERE simulation_id = "
                   f"'{final['simulation_id']}' ORDER BY sequence_number ASC LIMIT 5000")
            async with asyncio.timeout(120):
                while True:
                    rows = await query(client, settings, sql)
                    if len(rows) >= expected:
                        break
                    await asyncio.sleep(1)
            assert len(rows) == expected, (len(rows), final)
            assert len({row['event_id'] for row in rows}) == expected
            assert [row['sequence_number'] for row in rows] == list(range(1, expected + 1))
            assert {row['event_type'] for row in rows} == {kind.value for kind in EventType}
            latest_users = {}
            latest_drivers = {}
            for row in rows:
                if row['event_type'].startswith('RIDE_'):
                    latest_users[row['user_id']] = row['event_type']
                else:
                    latest_drivers[row['driver_id']] = row['event_type']
            assert sum(kind == 'DRIVER_WAITING' for kind in latest_drivers.values()) == final['in_memory']['waiting_drivers']
            assert sum(kind == 'DRIVER_ASSIGNED' for kind in latest_drivers.values()) == final['in_memory']['assigned_drivers']
            assert sum(kind in ('RIDE_REQUESTED', 'RIDE_ACCEPTED') for kind in latest_users.values()) == (
                final['in_memory']['waiting_users'] + final['in_memory']['users_in_ride'])
            await asyncio.sleep(0.2)
            assert service.status() == final
            results.append(final)
        assert results[0]['simulation_id'] != results[1]['simulation_id']
        after = await query(client, settings, 'SELECT COUNT(*) AS snapshots FROM ride_metrics')
        assert before == after, 'v1 row count changed during verification'
    print('PASS: fresh runs, 250 EPS, graceful drain, exact Pinot ingestion, state reconciliation, and v1 preservation.')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
