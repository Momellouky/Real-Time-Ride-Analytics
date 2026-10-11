#!/usr/bin/env python3
"""Publish one fresh snapshot and verify Kafka -> Pinot, using only the stdlib."""
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def compose(*args, input=None):
    return subprocess.run(
        ['docker', 'compose', *args], cwd=ROOT, input=input,
        text=True, capture_output=True, check=True, timeout=30,
    ).stdout


def query(sql):
    result = compose(
        'exec', '-T', 'pinot-broker', 'curl', '-fsS',
        '--max-time', '5', '-H', 'Content-Type: application/json',
        '-d', json.dumps({'sql': sql}), 'http://localhost:8099/query/sql',
    )
    payload = json.loads(result)
    if payload.get('exceptions'):
        raise RuntimeError(str(payload['exceptions']))
    table = payload['resultTable']
    return [dict(zip(table['dataSchema']['columnNames'], row, strict=True))
            for row in table['rows']]


def main():
    event = json.loads((ROOT / 'infra/pinot/sample-event.json').read_text())
    event.update(event_id=str(uuid4()), event_timestamp=time.time_ns() // 1_000_000)
    compose('exec', '-T', 'kafka', 'sh', '-ec',
            '/opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 '
            '--topic "$KAFKA_TOPIC" --producer-property acks=all',
            input=json.dumps(event) + '\n')
    print(f"Published {event['event_id']} to Kafka", flush=True)
    deadline = time.monotonic() + 120
    last_error = 'No matching row yet'
    while time.monotonic() < deadline:
        try:
            rows = query("SELECT * FROM ride_metrics WHERE event_id = "
                         f"'{event['event_id']}' LIMIT 2")
            if rows:
                if len(rows) != 1 or any(rows[0].get(k) != v for k, v in event.items()):
                    raise AssertionError(f'Snapshot mismatch: {rows}')
                history = query("SELECT event_id FROM ride_metrics "
                                "WHERE zone_id = 'ZONE_1' "
                                "AND event_timestamp >= ago('PT1H') "
                                f"AND event_id = '{event['event_id']}' LIMIT 2")
                if len(history) != 1:
                    raise AssertionError('Fresh event missing from last-hour history')
                print('PASS: exactly one matching snapshot and last-hour query verified.')
                print(json.dumps(rows[0], indent=2))
                return
        except (subprocess.CalledProcessError, RuntimeError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SystemExit(f'FAIL: ingestion timed out: {last_error}')


if __name__ == '__main__':
    main()
