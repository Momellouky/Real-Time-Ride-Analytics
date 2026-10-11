import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createDashboardPoller } from '../src/services/dashboard-poller.js';
import { pollingInterval, toSeries, validateDashboard } from '../src/domain/dashboard.js';
import { zeroMetrics } from '../src/domain/metrics.js';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function poller(request) {
  const callbacks = { request, onData: vi.fn(), onError: vi.fn(), onRefreshing: vi.fn(), interval: 2000 };
  return { ...createDashboardPoller(callbacks), ...callbacks };
}

it('loads immediately and refreshes at the configured interval', async () => {
  const run = poller(vi.fn().mockResolvedValue({ value: 1 }));
  run.start();
  await vi.advanceTimersByTimeAsync(0);
  expect(run.request).toHaveBeenCalledTimes(1);
  expect(run.onData).toHaveBeenCalledWith({ value: 1 });
  await vi.advanceTimersByTimeAsync(2000);
  expect(run.request).toHaveBeenCalledTimes(2);
  run.stop();
});

it('does not overlap slow requests', async () => {
  let resolve;
  const run = poller(vi.fn().mockReturnValue(new Promise((r) => { resolve = r; })));
  run.start();
  await vi.advanceTimersByTimeAsync(6000);
  expect(run.request).toHaveBeenCalledTimes(1);
  resolve({ value: 1 });
  await vi.advanceTimersByTimeAsync(2000);
  expect(run.request).toHaveBeenCalledTimes(2);
  run.stop();
});

it('keeps successful data on failure and recovers on a later poll', async () => {
  const request = vi.fn().mockResolvedValueOnce('first')
    .mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('recovered');
  const run = poller(request);
  run.start();
  await vi.advanceTimersByTimeAsync(2000);
  expect(run.onData.mock.calls).toEqual([['first']]);
  expect(run.onError).toHaveBeenCalledOnce();
  await vi.advanceTimersByTimeAsync(2000);
  expect(run.onData.mock.calls).toEqual([['first'], ['recovered']]);
  run.stop();
});

it('aborts on stop, clears the timer, and ignores late responses', async () => {
  let resolve;
  const run = poller(vi.fn().mockReturnValue(new Promise((r) => { resolve = r; })));
  run.start();
  const signal = run.request.mock.calls[0][0];
  run.stop();
  expect(signal.aborted).toBe(true);
  resolve('late');
  await vi.advanceTimersByTimeAsync(6000);
  expect(run.request).toHaveBeenCalledOnce();
  expect(run.onData).not.toHaveBeenCalled();
  expect(run.onError).not.toHaveBeenCalled();
});

it.each([[undefined, 2000], ['bad', 2000], ['0', 2000], ['100', 2000], ['2000', 2000], ['5000', 5000], ['2147483648', 2000]])(
  'validates poll configuration %s', (value, expected) => expect(pollingInterval(value)).toBe(expected));

it('maps irregular timestamps into raw points without fabricating samples', () => {
  expect(toSeries([{ event_timestamp: 1000, online_drivers: 20 },
    { event_timestamp: 9000, online_drivers: 30 }], 'online_drivers')).toEqual([
    { x: 1000, y: 20 }, { x: 9000, y: 30 }]);
});

it('accepts empty history and zero state', () => {
  const payload = { current: { zone_id: 'ZONE_1', ...zeroMetrics() }, history: [] };
  expect(validateDashboard(payload)).toBe(payload);
});

it.each([null, {}, { current: {}, history: [] },
  { current: { zone_id: 'ZONE_1', ...zeroMetrics() }, history: [{ event_timestamp: 1 }] },
  { current: { zone_id: 'ZONE_1', ...zeroMetrics() }, history: [
    { event_timestamp: 2, ...zeroMetrics() }, { event_timestamp: 1, ...zeroMetrics() }] },
])('rejects malformed dashboard responses', (payload) => {
  expect(() => validateDashboard(payload)).toThrow(/invalid dashboard data/);
});
