"""Publish valid manual lifecycles and verify all eight v2 event types in Pinot.

Adds ten immutable events under a fresh simulation ID; does not write to v1.
"""
import json
import subprocess
import time
from uuid import uuid4

from provision import compose


def query(sql):
    payload = json.loads(compose(
        'exec', '-T', 'pinot-broker', 'curl', '-fsS', '--max-time', '10',
        '-H', 'Content-Type: application/json', '-d',
        json.dumps({'sql': sql, 'queryOptions': 'enableNullHandling=true'}),
        'http://127.0.0.1:8099/query/sql'))
    if (payload.get('exceptions') or payload.get('numServersResponded', 0) == 0
            or payload.get('numServersResponded') != payload.get('numServersQueried')):
        raise RuntimeError(f'Incomplete Pinot query: {payload}')
    table = payload['resultTable']
    return [dict(zip(table['dataSchema']['columnNames'], row, strict=True))
            for row in table['rows']]


def build_events(simulation_id, timestamp):
    transitions = [
        ('DRIVER_CONNECTED', None, 'driver-001', None),
        ('DRIVER_WAITING', None, 'driver-001', None),
        ('RIDE_REQUESTED', 'user-001', None, 'ride-001'),
        ('RIDE_CANCELLED', 'user-001', None, 'ride-001'),
        ('RIDE_REQUESTED', 'user-001', None, 'ride-002'),
        ('RIDE_ACCEPTED', 'user-001', 'driver-001', 'ride-002'),
        ('DRIVER_ASSIGNED', 'user-001', 'driver-001', 'ride-002'),
        ('RIDE_COMPLETED', 'user-001', 'driver-001', 'ride-002'),
        ('DRIVER_WAITING', None, 'driver-001', 'ride-002'),
        ('DRIVER_DISCONNECTED', None, 'driver-001', None),
    ]
    return [dict(event_id=str(uuid4()), event_version=1, simulation_id=simulation_id,
                 sequence_number=sequence, event_timestamp=timestamp,
                 event_type=kind, zone_id='ZONE_1', user_id=user,
                 driver_id=driver, ride_id=ride)
            for sequence, (kind, user, driver, ride) in enumerate(transitions, 1)]


def verify_rows(rows, events):
    if len(rows) != len(events):
        raise AssertionError(f'Expected {len(events)} rows, got {len(rows)}')
    for actual, expected in zip(rows, events, strict=True):
        if any(actual.get(key) != value for key, value in expected.items()):
            raise AssertionError(f'Event mismatch: expected {expected}, got {actual}')


def main():
    simulation_id = 'smoke-' + str(uuid4())
    events = build_events(simulation_id, time.time_ns() // 1_000_000)
    compose('exec', '-T', 'kafka', '/opt/kafka/bin/kafka-console-producer.sh',
            '--bootstrap-server', 'kafka:9092', '--topic', 'ride-operations',
            '--producer-property', 'acks=all',
            input=''.join(json.dumps(event) + '\n' for event in events))
    print(f'Published {len(events)} events for {simulation_id}', flush=True)
    deadline = time.monotonic() + 120
    last_error = 'Waiting for ingestion'
    while time.monotonic() < deadline:
        try:
            rows = query("SELECT * FROM operations "
                         f"WHERE simulation_id = '{simulation_id}' "
                         'ORDER BY sequence_number ASC LIMIT 100')
            if len(rows) >= len(events):
                verify_rows(rows, events)
                counts = query('SELECT event_type, COUNT(*) AS event_count FROM operations '
                               f"WHERE simulation_id = '{simulation_id}' GROUP BY event_type")
                expected_counts = {event['event_type']: sum(e['event_type'] == event['event_type']
                                                           for e in events) for event in events}
                assert {row['event_type']: row['event_count'] for row in counts} == expected_counts, counts
                print('PASS: all eight event types, ten exact rows, nullable IDs, and sequence ordering verified.')
                print(json.dumps({'simulation_id': simulation_id, 'counts': expected_counts}, indent=2))
                return
        except (subprocess.CalledProcessError, RuntimeError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SystemExit(f'FAIL: ingestion timed out: {last_error}')


if __name__ == '__main__':
    main()
