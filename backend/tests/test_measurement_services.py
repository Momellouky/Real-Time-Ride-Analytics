import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.pinot_client import PinotClient, PinotQueryError
from app.services.pinot_metrics import PinotMetrics
from app.services.system_metrics import SystemMetrics


def test_latency_empty_and_single_sample():
    metrics = PinotMetrics()
    assert metrics.latency_summary() == dict(avg_ms=0, p95_ms=0, p99_ms=0, sample_count=0)
    metrics.record_latency(12.345)
    assert metrics.latency_summary() == dict(avg_ms=12.35, p95_ms=12.35, p99_ms=12.35, sample_count=1)


def test_percentiles_and_bounded_window():
    metrics = PinotMetrics()
    for value in reversed(range(1, 101)):
        metrics.record_latency(value)
    assert metrics.latency_summary() == dict(avg_ms=50.5, p95_ms=95, p99_ms=99, sample_count=100)
    for _ in range(500):
        metrics.record_latency(7)
    assert metrics.latency_summary() == dict(avg_ms=7, p95_ms=7, p99_ms=7, sample_count=500)


@pytest.mark.parametrize('size', [0, -1, True, 1.5])
def test_invalid_window_size(size):
    with pytest.raises(ValueError):
        PinotMetrics(size)


@pytest.mark.parametrize('value', [-1, float('inf'), float('nan')])
def test_invalid_latency(value):
    metrics = PinotMetrics()
    with pytest.raises(ValueError):
        metrics.record_latency(value)
    assert metrics.latency_summary()['sample_count'] == 0


@pytest.mark.parametrize('failure', [None, 'http', 'timeout', 'malformed'])
async def test_shared_client_times_success_and_failures(failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('timeout', request=request)
        if failure == 'http':
            return httpx.Response(503)
        return httpx.Response(200, json={} if failure else {
            'resultTable': {'dataSchema': {'columnNames': ['count']}, 'rows': [[3]]}})
    client = PinotClient('http://broker', transport=httpx.MockTransport(handler))
    try:
        with patch('app.services.pinot_client.perf_counter', side_effect=[1.0, 1.125]):
            if failure:
                with pytest.raises(PinotQueryError):
                    await client.query('SELECT test')
            else:
                assert await client.query('SELECT test') == [{'count': 3}]
        assert client.metrics.latency_summary() == dict(avg_ms=125, p95_ms=125, p99_ms=125, sample_count=1)
    finally:
        await client.close()


async def test_cancelled_query_records_one_sample_and_propagates_cancellation():
    entered = asyncio.Event()
    async def handler(request):
        entered.set()
        await asyncio.Event().wait()
    client = PinotClient('http://broker', transport=httpx.MockTransport(handler))
    try:
        task = asyncio.create_task(client.query('SELECT test'))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        summary = client.metrics.latency_summary()
        assert summary['sample_count'] == 1 and summary['avg_ms'] >= 0
    finally:
        await client.close()


async def test_concurrent_queries_keep_individual_timings():
    client = PinotClient('http://broker', transport=httpx.MockTransport(lambda request:
        httpx.Response(200, json={'resultTable': {'dataSchema': {'columnNames': ['count']}, 'rows': [[0]]}})))
    try:
        await asyncio.gather(*(client.query('SELECT test') for _ in range(20)))
        assert client.metrics.latency_summary()['sample_count'] == 20
    finally:
        await client.close()


def memory():
    return SimpleNamespace(total=16 * 1024 ** 3, used=6 * 1024 ** 3, percent=40)


def test_system_sampling_primes_cpu_and_returns_detached_snapshot():
    service = SystemMetrics()
    assert service.snapshot() is None
    with patch('app.services.system_metrics.psutil.cpu_percent', side_effect=[0, 37.5]) as cpu, \
         patch('app.services.system_metrics.psutil.virtual_memory', return_value=memory()):
        service._sample()
        assert service.snapshot()['cpu_percent'] is None
        service._sample()
        snapshot = service.snapshot()
        assert snapshot['cpu_percent'] == 37.5
        assert snapshot['memory_used_gb'] == 6 and snapshot['memory_total_gb'] == 16
        assert snapshot['memory_percent'] == 40
        assert snapshot['scope'] == 'os_visible_to_backend'
        assert snapshot['sampled_at_ms'] > 0
        snapshot['memory_percent'] = 99
        assert service.snapshot()['memory_percent'] == 40
        assert cpu.call_args_list[0].kwargs == {'interval': None}


@pytest.mark.parametrize('interval', [0, -1, .05, float('inf'), float('nan')])
def test_invalid_system_sampling_interval(interval):
    with pytest.raises(ValueError):
        SystemMetrics(interval)


async def test_sampler_runs_once_per_interval_and_stops():
    sampled = asyncio.Event()
    calls = 0
    def cpu(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            sampled.set()
        return 25
    service = SystemMetrics(interval_seconds=.1)
    with patch('app.services.system_metrics.psutil.cpu_percent', side_effect=cpu), \
         patch('app.services.system_metrics.psutil.virtual_memory', return_value=memory()):
        await service.start()
        task = service._task
        await service.start()
        assert service._task is task
        await asyncio.wait_for(sampled.wait(), 1)
        assert service.snapshot()['cpu_percent'] == 25
        await service.stop()
        await service.stop()
        assert task.done() and service._task is None
        await service.start()
        assert service.snapshot()['cpu_percent'] is None
        await service.stop()


def test_sampling_failure_retains_last_good_timestamp_and_recovers():
    service = SystemMetrics()
    with patch('app.services.system_metrics.psutil.cpu_percent', return_value=10), \
         patch('app.services.system_metrics.psutil.virtual_memory', return_value=memory()) as ram:
        service._try_sample()
        before = service.snapshot()
        ram.side_effect = OSError('proc unavailable')
        service._try_sample()
        assert service.snapshot() == before
        ram.side_effect = None
        service._try_sample()
        assert service.snapshot()['cpu_percent'] == 10


@pytest.mark.parametrize('startup_error', [False, True])
def test_app_owns_sampler_lifecycle_even_on_startup_failure(startup_error):
    sampler, kafka, pinot, generator = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    if startup_error:
        kafka.start.side_effect = RuntimeError('Kafka unavailable')
    with patch('app.main.SystemMetrics', return_value=sampler), \
         patch('app.main.MetricsKafkaProducer', return_value=kafka), \
         patch('app.main.PinotClient', return_value=pinot), \
         patch('app.main.GeneratorService', return_value=generator):
        app = create_app(Settings(_env_file=None))
        if startup_error:
            with pytest.raises(RuntimeError):
                with TestClient(app): pass
            sampler.start.assert_not_awaited()
        else:
            with TestClient(app) as client:
                assert client.get('/health').status_code == 200
                assert app.state.system_metrics is sampler
            sampler.start.assert_awaited_once()
        sampler.stop.assert_awaited_once()
        pinot.close.assert_awaited_once()
