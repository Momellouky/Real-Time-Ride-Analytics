import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, patch

from aiokafka.errors import KafkaConnectionError
import pytest

from app.generator import Simulation
from app.generator.events import EventType
from app.generator.scheduler import EventBudgetScheduler
from app.generator.service import GeneratorConflictError, GeneratorService, GeneratorState
from app.services.kafka_producer import KafkaPublishError, OperationsKafkaProducer


class Publisher:
    def __init__(self):
        self.acknowledged_events = 0
        self.events = []
        self.started = self.stopped = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.failure = None
        self.stop_failure = None

    async def start(self):
        self.started = True

    async def publish_batch(self, events):
        self.entered.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        self.events.extend(events)
        self.acknowledged_events += len(events)

    async def stop(self):
        self.stopped = True
        if self.stop_failure:
            raise self.stop_failure


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize('rate', [1, 7, 50, 100, 250, 500, 1000, 1237])
def test_budget_accounts_for_each_event_without_fractional_drift(rate):
    sim = Simulation(20, 10, seed=1)
    scheduler = EventBudgetScheduler(rate, 10)
    total = 0
    for tick in range(200):
        events = scheduler.next_batch(sim)
        total += len(events)
        assert total <= rate * (tick + 1) / 10
        sim.check_invariants()
    assert 0 <= rate * 20 - total <= 1


@pytest.mark.parametrize('rate', [0, -1, True, 2.5, '250', None])
def test_rate_validation(rate):
    with pytest.raises(ValueError, match='positive integer'):
        EventBudgetScheduler(rate, 10)


def test_warmup_uses_normal_driver_events_and_waits_for_ten_percent():
    sim = Simulation(10, 100)
    scheduler = EventBudgetScheduler(50, 100)
    batches = [scheduler.next_batch(sim) for _ in range(3)]
    assert not scheduler.warmed_up
    assert all(event.event_type in (EventType.DRIVER_CONNECTED, EventType.DRIVER_WAITING)
               for batch in batches for event in batch)
    assert sim.counts()['waiting_drivers'] == 7
    batch = scheduler.next_batch(sim)
    assert scheduler.warmed_up
    assert sim.counts()['waiting_drivers'] == 10
    assert len(batch) == 6


async def test_fresh_start_stop_and_runtime_stats():
    publishers = []
    def factory():
        publisher = Publisher()
        publishers.append(publisher)
        return publisher
    service = GeneratorService('unused', publisher_factory=factory)
    assert service.status()['status'] == 'STOPPED'
    assert (await service.stop())['simulation_id'] is None
    first = await service.start(5, 4, 50, seed=1)
    assert first['status'] == 'WARMING_UP'
    await publishers[0].entered.wait()
    await until(lambda: service.state == GeneratorState.RUNNING)
    with pytest.raises(GeneratorConflictError):
        await service.start()
    metadata = service.metadata
    with pytest.raises(FrozenInstanceError):
        metadata.user_pool_size = 100
    final = await service.stop()
    assert final['status'] == 'STOPPED'
    assert final['generated_events'] == final['published_events'] > 0
    assert final['last_error'] is None
    assert publishers[0].stopped
    count = len(publishers[0].events)
    await asyncio.sleep(0.12)
    assert service.status() == final and len(publishers[0].events) == count
    second = await service.start(2, 1, 100)
    assert second['simulation_id'] != first['simulation_id']
    assert second['generated_events'] == second['published_events'] == 0
    assert service.simulation.counts()['idle_users'] == 2
    assert service.simulation.counts()['offline_drivers'] == 1
    assert second['user_pool_size'] == 2
    assert await service.stop() == service.status()
    assert metadata.simulation_id == first['simulation_id']


async def test_stop_waits_for_inflight_batch_and_blocks_restart():
    publisher = Publisher()
    publisher.release.clear()
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    await service.start(10, 10, 50)
    await publisher.entered.wait()
    stop = asyncio.create_task(service.stop())
    await until(lambda: service.state == GeneratorState.STOPPING)
    generated = service.status()['generated_events']
    assert generated > 0 and service.status()['published_events'] == 0
    assert not stop.done() and not publisher.stopped
    with pytest.raises(GeneratorConflictError):
        await service.start()
    publisher.release.set()
    result = await stop
    assert result['generated_events'] == result['published_events'] == generated
    assert publisher.stopped and result['status'] == 'STOPPED'


async def test_cancelled_stop_caller_does_not_cancel_generator_cleanup():
    publisher = Publisher()
    publisher.release.clear()
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    await service.start(10, 10, 50)
    await publisher.entered.wait()
    stop = asyncio.create_task(service.stop())
    await until(lambda: service.state == GeneratorState.STOPPING)
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    publisher.release.set()
    await until(lambda: service.state == GeneratorState.STOPPED)
    assert publisher.stopped
    assert service.status()['generated_events'] == service.status()['published_events']


async def test_concurrent_start_only_creates_one_active_run():
    publishers = []
    def factory():
        publisher = Publisher()
        publishers.append(publisher)
        return publisher
    service = GeneratorService('unused', publisher_factory=factory)
    results = await asyncio.gather(service.start(2, 1, 50), service.start(2, 1, 50),
                                   return_exceptions=True)
    assert sum(isinstance(result, GeneratorConflictError) for result in results) == 1
    assert len(publishers) == 1
    await service.stop()


@pytest.mark.parametrize('drain_error', [False, True])
async def test_failures_halt_generation_and_remain_visible(drain_error):
    publisher = Publisher()
    if drain_error:
        publisher.stop_failure = KafkaPublishError('drain failed')
    else:
        publisher.failure = KafkaPublishError('publish failed')
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    await service.start(2, 1, 50)
    if drain_error:
        await publisher.entered.wait()
        await service.stop()
    else:
        await until(lambda: service.state == GeneratorState.ERROR)
    result = service.status()
    assert result['status'] == 'ERROR'
    assert result['last_error'] == ('drain failed' if drain_error else 'publish failed')
    assert publisher.stopped
    if not drain_error:
        assert result['generated_events'] > result['published_events'] == 0
    assert await service.stop() == result
    service.simulation.check_invariants()
    replacement = Publisher()
    service._factory = lambda: replacement
    restart = await service.start(1, 1, 50)
    assert restart['simulation_id'] != result['simulation_id']
    assert restart['last_error'] is None
    await service.stop()


async def test_startup_failure_closes_publisher_and_invalid_config_preserves_run():
    publisher = Publisher()
    publisher.start = AsyncMock(side_effect=KafkaPublishError('offline'))
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    with pytest.raises(KafkaPublishError):
        await service.start(2, 1, 50)
    assert service.state == GeneratorState.ERROR and publisher.stopped
    before = service.status()
    for kwargs in ({'user_count': 0}, {'driver_count': None}, {'target_events_per_second': 0}):
        with pytest.raises(ValueError):
            await service.start(**kwargs)
        assert service.status() == before


async def test_service_throughput_and_summary_logging(caplog):
    publisher = Publisher()
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    with caplog.at_level('INFO', logger='app.generator.service'):
        await service.start(50, 10, 250)
        start = asyncio.get_running_loop().time()
        await asyncio.sleep(2)
        result = await service.stop()
        elapsed = asyncio.get_running_loop().time() - start
    assert abs(result['published_events'] / elapsed - 250) <= 25
    assert abs(result['actual_events_per_second'] - 250) <= 25
    assert any('Generator finished' in record.message for record in caplog.records)


async def test_slow_publisher_limits_batch_size_instead_of_catching_up():
    publisher = Publisher()
    original = publisher.publish_batch
    async def slow(events):
        await asyncio.sleep(0.15)
        await original(events)
    publisher.publish_batch = slow
    service = GeneratorService('unused', publisher_factory=lambda: publisher)
    await service.start(20, 5, 50)
    await asyncio.sleep(0.6)
    result = await service.stop()
    assert result['published_events'] <= 20
    assert result['actual_events_per_second'] < 50


async def test_batch_enqueues_in_order_before_waiting_for_delivery():
    underlying = AsyncMock()
    futures = []
    async def send(*args, **kwargs):
        future = asyncio.get_running_loop().create_future()
        futures.append(future)
        return future
    underlying.send.side_effect = send
    producer = OperationsKafkaProducer('kafka:9092')
    sim = Simulation(1, 1)
    events = EventBudgetScheduler(50, 1).next_batch(sim)
    with patch('app.services.kafka_producer.AIOKafkaProducer', return_value=underlying) as factory:
        await producer.start()
        options = factory.call_args.kwargs
        assert options['acks'] == 'all' and options['enable_idempotence']
        assert options['linger_ms'] == 5
        task = asyncio.create_task(producer.publish_batch(events))
        await until(lambda: len(futures) == len(events))
        assert not task.done() and producer.acknowledged_events == 0
        assert [call.kwargs['value']['sequence_number'] for call in underlying.send.await_args_list] == list(range(1, len(events) + 1))
        assert all(call.args == ('ride-operations',) and call.kwargs['partition'] == 0
                   for call in underlying.send.await_args_list)
        for future in futures:
            future.set_result('ack')
        await task
        assert producer.acknowledged_events == len(events)
        await producer.stop()
        underlying.stop.assert_awaited_once()


@pytest.mark.parametrize('kind', ['enqueue', 'delivery', 'timeout'])
async def test_batch_failure_never_replays_or_cancels_delivery(kind):
    underlying = AsyncMock()
    futures = []
    async def send(*args, **kwargs):
        if kind == 'enqueue' and futures:
            raise KafkaConnectionError('enqueue failed')
        future = asyncio.get_running_loop().create_future()
        futures.append(future)
        if kind == 'delivery':
            future.set_exception(KafkaConnectionError('delivery failed'))
        return future
    async def stop():
        for future in futures:
            if not future.done():
                future.set_result('late ack')
        await asyncio.sleep(0)
    underlying.send.side_effect = send
    underlying.stop.side_effect = stop
    producer = OperationsKafkaProducer('unused', timeout=0.02)
    events = EventBudgetScheduler(50, 1).next_batch(Simulation(1, 1))
    with patch('app.services.kafka_producer.AIOKafkaProducer', return_value=underlying):
        await producer.start()
        with pytest.raises(KafkaPublishError):
            await producer.publish_batch(events)
        assert all(not future.cancelled() for future in futures)
        assert underlying.send.await_count <= len(events)
        await producer.stop()
        assert producer.acknowledged_events == (0 if kind == 'delivery' else len(futures))


async def test_publisher_requires_start_and_bounds_drain_timeout():
    producer = OperationsKafkaProducer('unused', timeout=0.01)
    with pytest.raises(KafkaPublishError, match='not started'):
        await producer.publish_batch([])
    underlying = AsyncMock()
    async def blocked():
        await asyncio.sleep(10)
    underlying.stop.side_effect = blocked
    with patch('app.services.kafka_producer.AIOKafkaProducer', return_value=underlying):
        await producer.start()
        with pytest.raises(KafkaPublishError, match='drain'):
            await producer.stop()
    assert producer._producer is None


def test_app_lifecycle_stops_generator_before_v1_clients():
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    generator, kafka, pinot = AsyncMock(), AsyncMock(), AsyncMock()
    order = []
    async def record(name):
        order.append(name)
    generator.stop.side_effect = lambda: None
    async def generator_stop():
        await record('generator')
    async def kafka_stop():
        await record('kafka')
    async def pinot_close():
        await record('pinot')
    generator.stop.side_effect, kafka.stop.side_effect, pinot.close.side_effect = generator_stop, kafka_stop, pinot_close
    with patch('app.main.GeneratorService', return_value=generator), \
         patch('app.main.MetricsKafkaProducer', return_value=kafka), \
         patch('app.main.PinotClient', return_value=pinot):
        with TestClient(create_app(Settings(_env_file=None))) as client:
            assert client.get('/health').status_code == 200
        generator.start.assert_not_awaited()
    assert order == ['generator', 'kafka', 'pinot']
