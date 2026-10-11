"""Process-wide, bounded timings for queries made by one shared Pinot client."""
from collections import deque
import math
from threading import Lock


class PinotMetrics:
    def __init__(self, max_samples: int = 500):
        if type(max_samples) is not int or max_samples < 1:
            raise ValueError('max_samples must be a positive integer')
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = Lock()

    def record_latency(self, latency_ms: float) -> None:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError('Latency must be finite and nonnegative')
        with self._lock:
            self._samples.append(latency_ms)

    def latency_summary(self) -> dict:
        with self._lock:
            values = sorted(self._samples)
        if not values:
            return dict(avg_ms=0.0, p95_ms=0.0, p99_ms=0.0, sample_count=0)
        # The plan's rounded-index percentile convention, without interpolation.
        return dict(avg_ms=round(sum(values) / len(values), 2),
                    p95_ms=round(values[round(.95 * (len(values) - 1))], 2),
                    p99_ms=round(values[round(.99 * (len(values) - 1))], 2),
                    sample_count=len(values))
