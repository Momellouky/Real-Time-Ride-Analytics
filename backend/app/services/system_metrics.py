"""Cached OS-visible CPU/RAM samples, independent of HTTP polling frequency."""
import asyncio
from contextlib import suppress
from dataclasses import dataclass, asdict
import logging
import math
import time

import psutil

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemSnapshot:
    sampled_at_ms: int
    cpu_percent: float | None
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    scope: str = 'os_visible_to_backend'


class SystemMetrics:
    def __init__(self, interval_seconds: float = 1.0):
        if not math.isfinite(interval_seconds) or interval_seconds < 0.1:
            raise ValueError('Sampling interval must be at least 0.1 seconds')
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._snapshot: SystemSnapshot | None = None
        self._primed = False

    def snapshot(self) -> dict | None:
        return asdict(self._snapshot) if self._snapshot else None

    def _sample(self) -> None:
        # Called on one event-loop thread: psutil keeps CPU baselines per thread.
        cpu = psutil.cpu_percent(interval=None)
        first = not self._primed
        self._primed = True
        memory = psutil.virtual_memory()
        self._snapshot = SystemSnapshot(
            sampled_at_ms=time.time_ns() // 1_000_000,
            cpu_percent=None if first else cpu,
            memory_percent=memory.percent,
            memory_used_gb=round(memory.used / 1024 ** 3, 2),
            memory_total_gb=round(memory.total / 1024 ** 3, 2))

    def _try_sample(self) -> None:
        try:
            self._sample()
        except (OSError, psutil.Error):
            # Preserve timestamped last-good data; never invent zero utilization.
            logger.warning('Unable to sample system metrics', exc_info=True)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._primed = False
        self._try_sample()
        self._task = asyncio.create_task(self._run(), name='system-metrics')

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            self._try_sample()

    async def stop(self) -> None:
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
