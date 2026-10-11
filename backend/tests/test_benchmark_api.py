from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.generator.service import RunMetadata
from app.main import create_app
from app.queries.operations import ingestion_metrics
from app.services.pinot_client import PinotQueryError
from app.services.pinot_metrics import PinotMetrics


@pytest.fixture
def api():
    metadata = RunMetadata('sim-one', 100, 20, 250, 4_000_000)
    status = dict(status='RUNNING', target_events_per_second=250, actual_events_per_second=240.5,
                  generated_events=120, published_events=115, last_error=None)
    generator = SimpleNamespace(metadata=metadata, status=lambda: status, stop=AsyncMock())
    pinot = SimpleNamespace(query=AsyncMock(return_value=[dict(total_ingested_events=110,
        latest_event_timestamp=4_999_000)]), metrics=PinotMetrics(), close=AsyncMock())
    system = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), snapshot=Mock(return_value=dict(
        sampled_at_ms=4_999_000, cpu_percent=30, memory_percent=60, memory_used_gb=8,
        memory_total_gb=16, scope='os_visible_to_backend')))
    with patch('app.main.GeneratorService', return_value=generator), \
         patch('app.main.PinotClient', return_value=pinot), \
         patch('app.main.MetricsKafkaProducer', return_value=AsyncMock()), \
         patch('app.main.SystemMetrics', return_value=system), \
         patch('app.api.benchmark.time.time_ns', return_value=5_000_000_000_000):
        with TestClient(create_app(Settings(_env_file=None))) as client:
            yield client, generator, status, pinot, system


def test_combines_runtime_pinot_latency_and_cached_system_metrics(api):
    client, _, _, pinot, system = api
    pinot.metrics.record_latency(10)
    body = client.get('/api/v2/benchmark/metrics').json()
    assert body['simulation_id'] == 'sim-one' and body['as_of_ms'] == 5_000_000
    assert body['generator']['actual_events_per_second'] == 240.5
    assert body['generator']['published_events'] == 115
    assert body['pinot']['total_ingested_events'] == 110
    assert body['pinot']['events_not_yet_visible'] == 10
    assert body['pinot']['ingestion_lag_ms'] == 1000
    assert body['pinot']['query_latency']['sample_count'] == 1
    assert body['system']['scope'] == 'os_visible_to_backend'
    assert 'in_memory' not in body['generator']
    system.snapshot.assert_called_once()
    sql = pinot.query.call_args.args[0]
    assert "simulation_id = 'sim-one'" in sql and "zone_id = 'ZONE_1'" in sql
    assert 'event_timestamp <= 5000000' in sql
    assert pinot.query.call_args.kwargs['options']['enableNullHandling'] == 'true'


def test_no_run_skips_pinot_and_retains_shared_latency_and_system(api):
    client, generator, status, pinot, _ = api
    generator.metadata = None
    status.update(status='STOPPED', target_events_per_second=0, actual_events_per_second=0,
                  generated_events=0, published_events=0)
    pinot.metrics.record_latency(5)
    response = client.get('/api/v2/benchmark/metrics')
    assert response.status_code == 200
    body = response.json()
    assert body['simulation_id'] is None
    assert body['pinot']['total_ingested_events'] == 0
    assert body['pinot']['ingestion_lag_ms'] is None
    assert body['pinot']['query_latency']['sample_count'] == 1
    pinot.query.assert_not_awaited()


@pytest.mark.parametrize('state', ['WARMING_UP', 'RUNNING', 'STOPPING', 'STOPPED', 'ERROR'])
def test_current_or_last_run_is_retained_in_every_lifecycle_state(api, state):
    client, _, status, _, _ = api
    status['status'] = state
    status['last_error'] = 'Kafka failed' if state == 'ERROR' else None
    body = client.get('/api/v2/benchmark/metrics').json()
    assert body['simulation_id'] == 'sim-one'
    assert body['generator']['status'] == state
    assert body['generator']['last_error'] == status['last_error']


def test_no_visible_events_has_unknown_freshness_and_full_backlog(api):
    client, _, _, pinot, _ = api
    pinot.query.return_value = [dict(total_ingested_events=0, latest_event_timestamp=None)]
    body = client.get('/api/v2/benchmark/metrics').json()
    assert body['pinot']['latest_event_timestamp'] is None
    assert body['pinot']['ingestion_lag_ms'] is None
    assert body['pinot']['events_not_yet_visible'] == 120


def test_backlog_never_negative(api):
    client, _, status, _, _ = api
    status['generated_events'] = 100
    assert client.get('/api/v2/benchmark/metrics').json()['pinot']['events_not_yet_visible'] == 0


def test_clock_regression_does_not_produce_negative_freshness(api):
    client, _, _, pinot, _ = api
    pinot.query.return_value = [dict(total_ingested_events=1, latest_event_timestamp=5_000_000)]
    with patch('app.api.benchmark.time.time_ns', side_effect=[5_000_000_000_000, 4_999_000_000_000]):
        assert client.get('/api/v2/benchmark/metrics').json()['pinot']['ingestion_lag_ms'] == 0


def test_counters_are_sampled_after_ingestion_query(api):
    client, _, status, pinot, _ = api
    async def query(*args, **kwargs):
        status['generated_events'] = 130
        return [dict(total_ingested_events=125, latest_event_timestamp=4_999_000)]
    pinot.query.side_effect = query
    body = client.get('/api/v2/benchmark/metrics').json()
    assert body['generator']['generated_events'] == 130
    assert body['pinot']['events_not_yet_visible'] == 5


def test_run_switch_rejects_old_result_then_queries_new_run(api):
    client, generator, _, pinot, _ = api
    async def switch(*args, **kwargs):
        generator.metadata = RunMetadata('sim-two', 10, 2, 50, 4_900_000)
        return [dict(total_ingested_events=110, latest_event_timestamp=4_999_000)]
    pinot.query.side_effect = switch
    assert client.get('/api/v2/benchmark/metrics').status_code == 409
    pinot.query.side_effect = None
    body = client.get('/api/v2/benchmark/metrics').json()
    assert body['simulation_id'] == 'sim-two'
    assert "simulation_id = 'sim-two'" in pinot.query.call_args.args[0]


def test_query_failure_is_503_without_zero_fallback(api):
    client, _, _, pinot, _ = api
    pinot.query.side_effect = PinotQueryError('Failed')
    response = client.get('/api/v2/benchmark/metrics')
    assert response.status_code == 503
    assert 'temporarily unavailable' in response.json()['detail']


@pytest.mark.parametrize('rows', [[], [{}, {}], {}, [{}],
    [dict(total_ingested_events=-1, latest_event_timestamp=None)],
    [dict(total_ingested_events=True, latest_event_timestamp=4_999_000)],
    [dict(total_ingested_events='1', latest_event_timestamp=4_999_000)],
    [dict(total_ingested_events=1, latest_event_timestamp=None)],
    [dict(total_ingested_events=1, latest_event_timestamp=5_000_001)],
    [dict(total_ingested_events=1, latest_event_timestamp=True)],
    [dict(total_ingested_events=1, latest_event_timestamp=-1)],
    [dict(total_ingested_events=0, latest_event_timestamp=0)]])
def test_malformed_aggregates_are_503(api, rows):
    client, _, _, pinot, _ = api
    pinot.query.return_value = rows
    assert client.get('/api/v2/benchmark/metrics').status_code == 503


def test_missing_or_priming_system_measurement_is_explicit(api):
    client, _, _, _, system = api
    system.snapshot.return_value = None
    assert client.get('/api/v2/benchmark/metrics').json()['system'] is None
    system.snapshot.return_value = dict(sampled_at_ms=4_999_000, cpu_percent=None,
        memory_percent=60, memory_used_gb=8, memory_total_gb=16, scope='os_visible_to_backend')
    assert client.get('/api/v2/benchmark/metrics').json()['system']['cpu_percent'] is None


@pytest.mark.parametrize('run', ["sim-one' OR 1=1 --", '', None])
def test_query_builder_rejects_unsafe_run_identifiers(run):
    with pytest.raises(ValueError):
        ingestion_metrics(run, 5_000_000)
