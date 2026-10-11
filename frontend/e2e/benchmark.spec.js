import { test, expect } from '@playwright/test';

const business = id => ({ run: id ? { simulation_id: id, user_pool_size: 100, driver_pool_size: 10,
  target_events_per_second: 250, started_at: Date.now() } : null,
  generator_status: id ? 'RUNNING' : 'STOPPED', as_of_ms: Date.now(), observed_users: 0,
  metrics: { total_users: id ? 100 : 0, active_users: 0, online_drivers: 0, waiting_drivers: 0,
    ride_requests: 0, accepted_rides: 0, cancelled_rides: 0, completed_rides: 0 },
  driver_states: { connected: 0, waiting: 0, assigned: 0, offline: id ? 10 : 0 },
  ride_history: [], event_rate: [] });
const measurement = (id = 'sim-one', eps = 249.5) => ({ simulation_id: id, as_of_ms: Date.now(),
  generator: { status: id ? 'RUNNING' : 'STOPPED', target_events_per_second: id ? 250 : 0,
    actual_events_per_second: id ? eps : 0, generated_events: id ? 100 : 0, published_events: id ? 95 : 0, last_error: null },
  pinot: { total_ingested_events: id ? 90 : 0, events_not_yet_visible: id ? 10 : 0,
    latest_event_timestamp: id ? Date.now() - 100 : null, ingestion_lag_ms: id ? 100 : null,
    query_latency: { avg_ms: 20, p95_ms: 30, p99_ms: 40, sample_count: 100 } },
  system: { sampled_at_ms: Date.now() - 100, cpu_percent: 25, memory_percent: 50,
    memory_used_gb: 8, memory_total_gb: 16, scope: 'os_visible_to_backend' } });
const card = (page, field) => page.locator(`[data-benchmark="${field}"] .benchmark-value`);

test('observability polls, recovers independently, resets history, and fits mobile', async ({ page }) => {
  const failures = []; page.on('pageerror', err => failures.push(err.message));
  let id = 'sim-one', broken = false, requests = 0, businessRequests = 0;
  await page.route('**/api/v2/dashboard', route => { businessRequests++; return route.fulfill({ json: business(id) }); });
  await page.route('**/api/v2/benchmark/metrics', route => {
    requests++;
    return route.fulfill(broken ? { status: 503, json: { detail: 'Pinot temporarily unavailable' } } : { json: measurement(id) });
  });
  await page.goto('/dashboard-v2');
  await expect(card(page, 'actual')).toHaveText('249.5');
  await expect(page.locator('.benchmark-card')).toHaveCount(9);
  await expect(page.locator('.benchmark-chart canvas')).toHaveCount(5);
  await expect(page.locator('.benchmark-context')).toContainText('2 browser observations');
  broken = true;
  await expect(page.getByRole('alert')).toContainText('Unable to refresh observability');
  await expect(card(page, 'actual')).toHaveText('249.5');
  const before = businessRequests;
  await expect.poll(() => businessRequests).toBeGreaterThan(before);
  broken = false;
  await expect(page.getByRole('alert')).toHaveCount(0);
  id = 'sim-two';
  await expect(page.getByTestId('benchmark-run-id')).toHaveText('sim-two');
  await expect(page.locator('.benchmark-context')).toContainText('1 browser observations');
  await page.screenshot({ path: 'test-results/observability-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/observability-mobile.png', fullPage: true });
  await page.getByRole('link', { name: 'Generator', exact: true }).click();
  const stopped = requests; await page.waitForTimeout(2500); expect(requests).toBe(stopped);
  expect(failures).toEqual([]);
});

test('observability handles initial failure, retry, unknown samples, and stopped rates', async ({ page }) => {
  let failed = true, stopped = false;
  await page.route('**/api/v2/dashboard', route => route.fulfill({ json: business(null) }));
  await page.route('**/api/v2/benchmark/metrics', route => {
    if (failed) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } });
    const data = measurement(stopped ? 'sim-stopped' : null);
    if (stopped) data.generator.status = 'STOPPED';
    else data.system.cpu_percent = null;
    return route.fulfill({ json: data });
  });
  await page.goto('/dashboard-v2');
  await expect(page.getByRole('alert')).toContainText('Unable to refresh observability');
  await expect(page.locator('.event-card')).toHaveCount(8);
  failed = false; await page.getByRole('button', { name: 'Retry observability' }).click();
  await expect(card(page, 'cpu')).toHaveText('—');
  await expect(card(page, 'lag')).toHaveText('—');
  await expect(page.getByTestId('benchmark-run-id')).toHaveText('No simulation run');
  stopped = true;
  await expect(page.locator('.benchmark-panel')).toContainText('Production has stopped.');
  await expect(page.locator('[data-benchmark="actual"]')).toContainText('Final acknowledged rate');
});

test('observability does not overlap slow requests', async ({ page }) => {
  let active = 0, maximum = 0, count = 0;
  await page.route('**/api/v2/dashboard', route => route.fulfill({ json: business('sim-one') }));
  await page.route('**/api/v2/benchmark/metrics', async route => {
    active++; count++; maximum = Math.max(maximum, active);
    await new Promise(resolve => setTimeout(resolve, 2500));
    active--; await route.fulfill({ json: measurement() });
  });
  await page.goto('/dashboard-v2');
  await expect(card(page, 'actual')).toHaveText('249.5');
  await expect.poll(() => count).toBeGreaterThan(1);
  expect(maximum).toBe(1);
  await page.goto('/settings');
});

test('live observability API renders real system samples and latency', async ({ page, request }) => {
  expect((await request.get('/api/metrics/current')).status()).toBe(200);
  const response = await request.get('/api/v2/benchmark/metrics');
  expect(response.status()).toBe(200);
  const data = await response.json();
  await page.goto('/dashboard-v2');
  await expect(page.locator('.benchmark-card')).toHaveCount(9);
  await expect(page.locator('.benchmark-chart canvas')).toHaveCount(5);
  await expect(card(page, 'cpu')).not.toHaveText('—', { timeout: 10000 });
  await expect(card(page, 'memory')).toContainText('GiB');
  await expect(card(page, 'p95')).toContainText('ms');
  await expect(page.getByTestId('benchmark-run-id')).toHaveText(data.simulation_id || 'No simulation run');
});
