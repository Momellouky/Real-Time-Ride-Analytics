import { onMounted, onUnmounted, ref } from 'vue';
import { getBenchmarkMetrics } from '../services/api.js';
import { createDashboardPoller } from '../services/dashboard-poller.js';
import { appendBenchmarkHistory, validateBenchmark } from '../domain/benchmark.js';

export function useBenchmark() {
  const data = ref(null), history = ref([]), error = ref(''), refreshing = ref(false), updatedAt = ref(null);
  const interval = 2000;
  const poller = createDashboardPoller({
    interval,
    request: async signal => validateBenchmark(await getBenchmarkMetrics(signal)),
    onData(payload) {
      const now = Date.now();
      history.value = appendBenchmarkHistory(history.value, data.value?.simulation_id, payload, now);
      data.value = payload; updatedAt.value = now; error.value = '';
    },
    onError(failure) { error.value = failure.message; },
    onRefreshing(value) { refreshing.value = value; },
  });
  onMounted(poller.start);
  onUnmounted(poller.stop);
  return { data, history, error, refreshing, updatedAt, interval, refresh: poller.refresh };
}
