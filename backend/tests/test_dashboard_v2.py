from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.generator.service import GeneratorService, RunMetadata, GeneratorState
from app.main import create_app
from app.models.operations import OperationsAnalyticsResult, DriverCounts, RideCounts
from app.services.pinot_client import PinotQueryError


@pytest.fixture
def api():
    service = GeneratorService('unused')
    app = create_app(Settings(_env_file=None))
    analytics = AsyncMock()
    with patch('app.main.GeneratorService', return_value=service), \
         patch('app.main.MetricsKafkaProducer', return_value=AsyncMock()), \
         patch('app.main.PinotClient', return_value=AsyncMock()), \
         patch('app.api.dashboard_v2.OperationsAnalytics', return_value=analytics):
        with TestClient(app) as client:
            yield client, service, analytics


def configure(service, analytics):
    service.metadata = RunMetadata('sim-first', 100, 10, 250, 1000)
    analytics.read.return_value = OperationsAnalyticsResult(
        simulation_id='sim-first', as_of_ms=10000,
        recent_rides=RideCounts(requested=9, accepted=5, cancelled=2, completed=3),
        drivers=DriverCounts(connected=1, waiting=2, assigned=3, disconnected=1),
        active_users=8, observed_users=12, ride_history=[], event_rate=[])


def test_before_first_run_no_pinot_queries(api):
    client, _, analytics = api
    response = client.get('/api/v2/dashboard')
    assert response.status_code == 200
    body = response.json()
    assert body['run'] is None and body['generator_status'] == 'STOPPED'
    assert not any(body['metrics'].values())
    assert body['ride_history'] == body['event_rate'] == []
    analytics.read.assert_not_awaited()


@pytest.mark.parametrize('state', list(GeneratorState))
def test_combines_metadata_and_pinot_with_stopped_run_retained(api, state):
    client, service, analytics = api
    configure(service, analytics)
    service.state = state
    service.last_error = 'Publish failed' if state == GeneratorState.ERROR else None
    body = client.get('/api/v2/dashboard').json()
    assert body['run']['simulation_id'] == 'sim-first'
    assert body['generator_status'] == state
    assert body['metrics'] == dict(total_users=100, active_users=8, online_drivers=6,
        waiting_drivers=2, ride_requests=9, accepted_rides=5, cancelled_rides=2, completed_rides=3)
    assert body['driver_states'] == dict(connected=1, waiting=2, assigned=3, offline=4)
    assert body['observed_users'] == 12
    assert 'in_memory' not in body
    args, kwargs = analytics.read.call_args
    assert args == ('sim-first',) and kwargs['as_of_ms'] == body['as_of_ms']
    service.state = GeneratorState.STOPPED


def test_run_change_during_queries_rejects_mixed_response(api):
    client, service, analytics = api
    configure(service, analytics)
    old_result = analytics.read.return_value
    async def change(*args, **kwargs):
        service.metadata = RunMetadata('sim-second', 20, 5, 50, 2000)
        return old_result
    analytics.read.side_effect = change
    response = client.get('/api/v2/dashboard')
    assert response.status_code == 409
    assert 'run changed' in response.json()['detail']


def test_query_failure_returns_503_without_diagnostic_fallback(api):
    client, service, analytics = api
    configure(service, analytics)
    analytics.read.side_effect = PinotQueryError('Unavailable')
    assert client.get('/api/v2/dashboard').status_code == 503


@pytest.mark.parametrize('field', ['active_users', 'observed_users', 'drivers'])
def test_impossible_population_is_rejected(api, field):
    client, service, analytics = api
    configure(service, analytics)
    changes = {field: DriverCounts(waiting=11) if field == 'drivers' else 101}
    analytics.read.return_value = analytics.read.return_value.model_copy(update=changes)
    assert client.get('/api/v2/dashboard').status_code == 503


def test_before_ingestion_pool_is_offline_and_counters_are_zero(api):
    client, service, analytics = api
    configure(service, analytics)
    analytics.read.return_value = OperationsAnalyticsResult(simulation_id='sim-first', as_of_ms=10000,
        recent_rides=RideCounts(), drivers=DriverCounts(), active_users=0, observed_users=0,
        ride_history=[], event_rate=[])
    body = client.get('/api/v2/dashboard').json()
    assert body['metrics']['total_users'] == 100
    assert body['metrics']['online_drivers'] == 0
    assert body['driver_states']['offline'] == 10
