"""Read-only benchmark API smoke test against existing Pinot and generator state."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.request import urlopen

from fastapi.testclient import TestClient

from app.generator.service import RunMetadata
from app.main import create_app


def main():
    with urlopen('http://backend:8000/api/v2/generator/status', timeout=10) as response:
        runtime = json.load(response)
    metadata = None
    if runtime['simulation_id']:
        metadata = RunMetadata(runtime['simulation_id'], runtime['user_pool_size'],
            runtime['driver_pool_size'], runtime['target_events_per_second'], 0)
    generator = SimpleNamespace(metadata=metadata, status=lambda: runtime, stop=AsyncMock())
    with patch('app.main.GeneratorService', return_value=generator), \
         patch('app.main.MetricsKafkaProducer', return_value=AsyncMock()):
        app = create_app()
        with TestClient(app) as client:
            response = client.get('/api/v2/benchmark/metrics')
            assert response.status_code == 200, response.text
            body = response.json()
            assert body['simulation_id'] == runtime['simulation_id']
            assert body['system']['scope'] == 'os_visible_to_backend'
            if metadata and runtime['status'] == 'STOPPED':
                assert body['pinot']['total_ingested_events'] == runtime['published_events'], body
            print('Existing run:', json.dumps(body))
            generator.metadata = RunMetadata('sim-benchmark-verification-empty', 1, 1, 1, 0)
            response = client.get('/api/v2/benchmark/metrics')
            assert response.status_code == 200, response.text
            empty = response.json()['pinot']
            assert empty['total_ingested_events'] == 0 and empty['latest_event_timestamp'] is None
            assert empty['ingestion_lag_ms'] is None
            print('Empty run: null timestamp/freshness verified')
            generator.metadata = None
            runtime.update(status='STOPPED', target_events_per_second=0,
                           actual_events_per_second=0, generated_events=0, published_events=0)
            before = response.json()['pinot']['query_latency']['sample_count']
            no_run = client.get('/api/v2/benchmark/metrics').json()
            assert no_run['simulation_id'] is None
            assert no_run['pinot']['query_latency']['sample_count'] == before
            print('No run: no extra Pinot queries verified')


if __name__ == '__main__':
    main()
