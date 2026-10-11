from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.generator.service import GeneratorConflictError, GeneratorService
from app.main import create_app
from app.services.kafka_producer import KafkaPublishError


class Publisher:
    acknowledged_events = 0
    async def start(self): pass
    async def stop(self): pass
    async def publish_batch(self, events):
        self.acknowledged_events += len(events)


@pytest.fixture
def api():
    app = create_app(Settings(_env_file=None))
    service = GeneratorService('unused', publisher_factory=Publisher)
    kafka, pinot = AsyncMock(), AsyncMock()
    with patch('app.main.GeneratorService', return_value=service), \
         patch('app.main.MetricsKafkaProducer', return_value=kafka), \
         patch('app.main.PinotClient', return_value=pinot):
        with TestClient(app) as client:
            yield client, service


def test_idle_status_and_repeated_stop(api):
    client, service = api
    status = client.get('/api/v2/generator/status')
    assert status.status_code == 200
    data = status.json()
    assert data['status'] == 'STOPPED' and data['simulation_id'] is None
    assert data['generated_events'] == data['published_events'] == 0
    assert data['in_memory']['idle_users'] == 0
    assert client.post('/api/v2/generator/stop').json() == data
    assert service.simulation is None


def test_start_conflict_graceful_stop_and_fresh_restart(api):
    client, service = api
    config = dict(user_count=10, driver_count=2, target_events_per_second=250)
    response = client.post('/api/v2/generator/start', json=config)
    assert response.status_code == 202
    first = response.json()
    assert first['status'] == 'WARMING_UP'
    assert first['user_pool_size'] == 10 and first['driver_pool_size'] == 2
    assert client.post('/api/v2/generator/start', json=config).status_code == 409
    final = client.post('/api/v2/generator/stop')
    assert final.status_code == 200 and final.json()['status'] == 'STOPPED'
    assert final.json()['generated_events'] == final.json()['published_events']
    assert client.get('/api/v2/generator/status').json() == final.json()
    assert client.post('/api/v2/generator/stop').json() == final.json()
    second = client.post('/api/v2/generator/start', json=config).json()
    assert second['simulation_id'] != first['simulation_id']
    service.simulation.check_invariants()


@pytest.mark.parametrize('field', ['user_count', 'driver_count', 'target_events_per_second'])
@pytest.mark.parametrize('value', [0, -1, True, '250', 1.5, None])
def test_invalid_config_rejected_before_start(api, field, value):
    client, service = api
    config = dict(user_count=10, driver_count=2, target_events_per_second=50)
    config[field] = value
    assert client.post('/api/v2/generator/start', json=config).status_code == 422
    assert service.simulation is None


@pytest.mark.parametrize('config', [{}, {'user_count': 10, 'driver_count': 2},
    dict(user_count=10, driver_count=2, target_events_per_second=50, zone_id='ZONE_2'),
    dict(user_count=10, driver_count=2, target_events_per_second=50, simulation_id='supplied')])
def test_complete_supported_config_required(api, config):
    client, service = api
    assert client.post('/api/v2/generator/start', json=config).status_code == 422
    assert service.simulation is None


def test_custom_rate_above_1000_is_allowed(api):
    client, service = api
    response = client.post('/api/v2/generator/start', json=dict(user_count=10, driver_count=2,
                                                              target_events_per_second=1250))
    assert response.status_code == 202 and response.json()['target_events_per_second'] == 1250
    assert client.post('/api/v2/generator/stop').status_code == 200


def test_start_failure_has_generator_specific_message(api):
    client, service = api
    with patch.object(service, 'start', AsyncMock(side_effect=KafkaPublishError('internal broker details'))):
        response = client.post('/api/v2/generator/start', json=dict(user_count=10, driver_count=2,
                                                                  target_events_per_second=50))
    assert response.status_code == 503
    assert 'Unable to start the generator' in response.json()['detail']
    assert 'internal broker details' not in response.text


def test_failed_drain_is_visible_in_stop_response(api):
    client, service = api
    status = service.status() | {'status': 'ERROR', 'last_error': 'Unable to drain operations producer'}
    with patch.object(service, 'stop', AsyncMock(return_value=status)):
        response = client.post('/api/v2/generator/stop')
    assert response.status_code == 200
    assert response.json()['status'] == 'ERROR'
    assert response.json()['last_error']
