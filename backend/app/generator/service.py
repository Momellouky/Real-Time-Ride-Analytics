"""Single-process generator lifecycle owned by the FastAPI application."""
import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
import time
from typing import Protocol

from app.services.kafka_producer import OperationsKafkaProducer
from .scheduler import EventBudgetScheduler
from .simulation import Simulation

logger = logging.getLogger(__name__)


class GeneratorState(StrEnum):
    STOPPED = 'STOPPED'
    WARMING_UP = 'WARMING_UP'
    RUNNING = 'RUNNING'
    STOPPING = 'STOPPING'
    ERROR = 'ERROR'


class GeneratorConflictError(RuntimeError):
    pass


class BatchPublisher(Protocol):
    acknowledged_events: int
    async def start(self) -> None: ...
    async def publish_batch(self, events) -> None: ...
    async def stop(self) -> None: ...


@dataclass(frozen=True)
class RunMetadata:
    simulation_id: str
    user_pool_size: int
    driver_pool_size: int
    target_events_per_second: int
    started_at: int


class GeneratorService:
    def __init__(self, bootstrap_servers: str, timeout: float = 10.0, *,
                 publisher_factory: Callable[[], BatchPublisher] | None = None):
        self._factory = publisher_factory or (lambda: OperationsKafkaProducer(bootstrap_servers, timeout))
        self.state = GeneratorState.STOPPED
        self.simulation: Simulation | None = None
        self.metadata: RunMetadata | None = None
        self.last_error: str | None = None
        self._lock = asyncio.Lock()
        self._stop_requested = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._publisher: BatchPublisher | None = None
        self._samples: deque[tuple[float, int]] = deque()
        self._final_eps = 0.0

    async def start(self, user_count: int = 10_000, driver_count: int = 2_000,
                    target_events_per_second: int = 250, *, seed: int | None = None) -> dict:
        async with self._lock:
            if self.state in (GeneratorState.WARMING_UP, GeneratorState.RUNNING, GeneratorState.STOPPING):
                raise GeneratorConflictError('Generator is already active')
            sim = Simulation(user_count, driver_count, seed=seed)
            scheduler = EventBudgetScheduler(target_events_per_second, driver_count)
            publisher = self._factory()
            self.simulation = sim
            self.metadata = RunMetadata(sim.simulation_id, user_count, driver_count,
                                        target_events_per_second, time.time_ns() // 1_000_000)
            self._publisher = publisher
            self.last_error = None
            self._final_eps = 0.0
            self._stop_requested = asyncio.Event()
            self.state = GeneratorState.WARMING_UP
            try:
                await publisher.start()
            except BaseException as exc:
                self.last_error = str(exc) or type(exc).__name__
                self.state = GeneratorState.ERROR
                try:
                    await publisher.stop()
                except Exception:
                    logger.exception('Operations producer cleanup after startup failure')
                raise
            self._samples = deque([(asyncio.get_running_loop().time(), 0)])
            self._task = asyncio.create_task(self._run(scheduler), name=f'generator-{sim.simulation_id}')
            return self.status()

    async def stop(self) -> dict:
        async with self._lock:
            task = self._task
            if task is None or task.done():
                return self.status()
            self.state = GeneratorState.STOPPING
            self._stop_requested.set()
        # Caller cancellation must not cancel an in-flight Kafka batch or cleanup.
        await asyncio.shield(task)
        return self.status()

    def _rate(self, now: float) -> float:
        if not self._samples or self._publisher is None:
            return 0.0
        cutoff = now - 5.0
        while len(self._samples) > 1 and self._samples[1][0] <= cutoff:
            self._samples.popleft()
        start, count = self._samples[0]
        return (self._publisher.acknowledged_events - count) / max(now - start, 0.1)

    def status(self) -> dict:
        sim, metadata = self.simulation, self.metadata
        active = self.state in (GeneratorState.WARMING_UP, GeneratorState.RUNNING, GeneratorState.STOPPING)
        return dict(simulation_id=metadata.simulation_id if metadata else None,
                    status=self.state.value,
                    target_events_per_second=metadata.target_events_per_second if metadata else 0,
                    actual_events_per_second=round(self._rate(asyncio.get_running_loop().time()) if active else self._final_eps, 2),
                    generated_events=sim.sequence_number if sim else 0,
                    published_events=self._publisher.acknowledged_events if self._publisher else 0,
                    user_pool_size=metadata.user_pool_size if metadata else 0,
                    driver_pool_size=metadata.driver_pool_size if metadata else 0,
                    in_memory=sim.counts() if sim else {}, last_error=self.last_error)

    async def _run(self, scheduler: EventBudgetScheduler) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        next_log = next_tick + 5.0
        try:
            while not self._stop_requested.is_set():
                events = scheduler.next_batch(self.simulation)
                if events:
                    await self._publisher.publish_batch(events)
                now = loop.time()
                self._samples.append((now, self._publisher.acknowledged_events))
                self._rate(now)
                if scheduler.warmed_up and not self._stop_requested.is_set():
                    self.state = GeneratorState.RUNNING
                if now >= next_log:
                    logger.info('Generator summary %s', self.status())
                    next_log = now + 5.0
                next_tick += scheduler.tick_seconds
                if next_tick < now:
                    next_tick = now + scheduler.tick_seconds
                try:
                    await asyncio.wait_for(self._stop_requested.wait(), max(0, next_tick - now))
                except TimeoutError:
                    pass
        except Exception as exc:
            self.last_error = str(exc) or type(exc).__name__
            logger.exception('Generator run failed: %s', self.simulation.simulation_id)
        finally:
            try:
                await self._publisher.stop()
            except Exception as exc:
                self.last_error = self.last_error or str(exc) or type(exc).__name__
                logger.exception('Generator drain failed')
            self._final_eps = self._rate(loop.time())
            self.state = GeneratorState.ERROR if self.last_error else GeneratorState.STOPPED
            logger.info('Generator finished %s', self.status())
