import { onMounted, onUnmounted, ref } from 'vue';
import { getDashboard } from '../services/api.js';
import { createDashboardPoller } from '../services/dashboard-poller.js';
import { pollingInterval, validateDashboard } from '../domain/dashboard.js';

export function useDashboard() {
  const data = ref(null);
  const error = ref('');
  const refreshing = ref(false);
  const updatedAt = ref(null);
  const interval = pollingInterval(import.meta.env.VITE_DASHBOARD_POLL_INTERVAL_MS);
  const poller = createDashboardPoller({
    request: async (signal) => validateDashboard(await getDashboard(signal)),
    onData(payload) { data.value = payload; error.value = ''; updatedAt.value = Date.now(); },
    onError(failure) { error.value = failure.message; },
    onRefreshing(value) { refreshing.value = value; },
    interval,
  });
  onMounted(poller.start);
  onUnmounted(poller.stop);
  return { data, error, refreshing, updatedAt, interval, refresh: poller.refresh };
}
