import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useMetricsStore } from '../src/stores/metrics.js';
import { METRICS, validateMetrics, zeroMetrics } from '../src/domain/metrics.js';
import { getCurrentMetrics, updateMetrics } from '../src/services/api.js';

vi.mock('../src/services/api.js', () => ({ getCurrentMetrics: vi.fn(), updateMetrics: vi.fn() }));
const snapshot = { zone_id: 'ZONE_1', event_id: 'old', event_timestamp: 1000,
  online_drivers: 75, ride_requests: 100, accepted_requests: 60, cancelled_requests: 15, waiting_drivers: 20 };

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); });

describe('metric validation', () => {
  it('allows zeros, equality boundaries, and pending requests', () => {
    expect(validateMetrics(zeroMetrics())).toEqual({});
    expect(validateMetrics(snapshot)).toEqual({});
    expect(validateMetrics({ ...snapshot, waiting_drivers: 75, cancelled_requests: 40 })).toEqual({});
  });
  for (const { field } of METRICS) {
    it.each(['', null, undefined, true, '20', -1, 0.5, 2147483648])(`rejects invalid ${field}: %s`, (value) => {
      expect(validateMetrics({ ...snapshot, [field]: value })[field]).toBeTruthy();
    });
  }
  it('rejects cross-field rule violations', () => {
    expect(validateMetrics({ ...snapshot, accepted_requests: 100 }).accepted_requests).toMatch(/must not exceed/);
    expect(validateMetrics({ ...snapshot, waiting_drivers: 76 }).waiting_drivers).toMatch(/must not exceed/);
  });
});

describe('settings store', () => {
  it('loads the current snapshot and submits all five values when only one changes', async () => {
    getCurrentMetrics.mockResolvedValue(snapshot);
    const accepted = { status: 'accepted', event_id: 'new', event_timestamp: 2000 };
    updateMetrics.mockResolvedValue(accepted);
    const store = useMetricsStore();
    await store.initialize();
    store.setValue('online_drivers', 76);
    await store.submit();
    expect(updateMetrics).toHaveBeenCalledExactlyOnceWith({ zone_id: 'ZONE_1',
      online_drivers: 76, ride_requests: 100, accepted_requests: 60, cancelled_requests: 15, waiting_drivers: 20 });
    expect(store.accepted).toEqual(accepted);
    expect(store.lastTimestamp).toBe(1000);
  });
  it('initializes empty data from the zero-valued API snapshot', async () => {
    getCurrentMetrics.mockResolvedValue({ zone_id: 'ZONE_1', event_id: null, event_timestamp: null, ...zeroMetrics() });
    const store = useMetricsStore();
    await store.initialize();
    expect(store.values).toEqual(zeroMetrics());
    expect(store.canSubmit).toBe(true);
  });
  it('blocks publishing after a load failure and permits retry', async () => {
    getCurrentMetrics.mockRejectedValueOnce(new Error('Service unavailable')).mockResolvedValueOnce(snapshot);
    const store = useMetricsStore();
    await store.initialize();
    await store.submit();
    expect(store.loadError).toBe('Service unavailable');
    expect(store.canSubmit).toBe(false);
    expect(updateMetrics).not.toHaveBeenCalled();
    await store.initialize();
    expect(store.loaded).toBe(true);
    expect(store.loadError).toBe('');
  });
  it('blocks invalid input and preserves editable values after publishing errors', async () => {
    getCurrentMetrics.mockResolvedValue(snapshot);
    updateMetrics.mockRejectedValue(new Error('Kafka unavailable'));
    const store = useMetricsStore();
    await store.initialize();
    store.setValue('waiting_drivers', 76);
    await store.submit();
    expect(updateMetrics).not.toHaveBeenCalled();
    store.setValue('waiting_drivers', 21);
    await store.submit();
    expect(store.submitError).toBe('Kafka unavailable');
    expect(store.values.waiting_drivers).toBe(21);
    expect(store.submitting).toBe(false);
    expect(store.accepted).toBeNull();
  });
  it('prevents duplicate submits and editing while awaiting acknowledgement', async () => {
    getCurrentMetrics.mockResolvedValue(snapshot);
    let resolve;
    updateMetrics.mockReturnValue(new Promise((r) => { resolve = r; }));
    const store = useMetricsStore();
    await store.initialize();
    const first = store.submit();
    await store.submit();
    store.setValue('online_drivers', 99);
    expect(store.values.online_drivers).toBe(75);
    expect(updateMetrics).toHaveBeenCalledTimes(1);
    resolve({ status: 'accepted', event_id: 'new', event_timestamp: 2000 });
    await first;
    store.setValue('online_drivers', 76);
    expect(store.accepted).toBeNull();
  });
  it('does not treat malformed current data as a usable zero state', async () => {
    getCurrentMetrics.mockResolvedValue({ zone_id: 'ZONE_1', online_drivers: 0 });
    const store = useMetricsStore();
    await store.initialize();
    expect(store.loaded).toBe(false);
    expect(store.loadError).toMatch(/invalid metric values/);
  });
  it('clears old submission feedback when loading a fresh snapshot', async () => {
    getCurrentMetrics.mockResolvedValue(snapshot);
    updateMetrics.mockResolvedValue({ status: 'accepted', event_id: 'new', event_timestamp: 2000 });
    const store = useMetricsStore();
    await store.initialize();
    await store.submit();
    expect(store.accepted).not.toBeNull();
    await store.initialize();
    expect(store.accepted).toBeNull();
    expect(store.submitError).toBe('');
  });
});
