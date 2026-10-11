import { afterEach, expect, it, vi } from 'vitest';
import { getCurrentMetrics, updateMetrics, getGeneratorStatus, startGenerator, stopGenerator } from '../src/services/api.js';

afterEach(() => vi.unstubAllGlobals());

it('sends JSON with all values', async () => {
  const payload = { zone_id: 'ZONE_1', online_drivers: 0 };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'accepted' }), { status: 202 }));
  vi.stubGlobal('fetch', fetch);
  await updateMetrics(payload);
  expect(fetch.mock.calls[0][0]).toBe('/api/metrics');
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'POST', body: JSON.stringify(payload),
    headers: { 'Content-Type': 'application/json' } });
});

it.each([
  [{ detail: 'Analytics are temporarily unavailable.' }, 503, /temporarily unavailable/],
  [{ detail: [{ loc: ['body', 'online_drivers'], msg: 'Must be an integer' }] }, 422, /online drivers: Must be an integer/],
])('formats backend errors readably', async (body, status, message) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
  await expect(getCurrentMetrics()).rejects.toThrow(message);
});

it('shows a connection error for network failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
  await expect(getCurrentMetrics()).rejects.toThrow(/Unable to reach/);
});

it('handles non-JSON responses', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 })));
  await expect(getCurrentMetrics()).rejects.toThrow(/unreadable response/);
});

it('uses the v2 control endpoints and status abort signal', async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ status: 'STOPPED' })));
  vi.stubGlobal('fetch', fetch);
  const controller = new AbortController();
  await getGeneratorStatus(controller.signal);
  const payload = { user_count: 10, driver_count: 2, target_events_per_second: 50 };
  await startGenerator(payload); await stopGenerator();
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/v2/generator/status', '/api/v2/generator/start', '/api/v2/generator/stop']);
  expect(fetch.mock.calls[1][1]).toMatchObject({ method: 'POST', body: JSON.stringify(payload) });
  expect(fetch.mock.calls[2][1]).toMatchObject({ method: 'POST' });
});

it('fetches benchmark metrics and propagates navigation cancellation', async () => {
  const { getBenchmarkMetrics } = await import('../src/services/api.js');
  const controller = new AbortController();
  const fetch = vi.fn().mockResolvedValue(new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await getBenchmarkMetrics(controller.signal);
  expect(fetch.mock.calls[0][0]).toBe('/api/v2/benchmark/metrics');
  const signal = fetch.mock.calls[0][1].signal;
  controller.abort();
  expect(signal.aborted).toBe(true);
});
