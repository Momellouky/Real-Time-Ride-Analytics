import { test, expect } from '@playwright/test';

const value = (page, field) => page.locator(`[data-metric="${field}"] .metric-value`);
const fixture = (id = 'sim-first', count = 5) => ({
  run: { simulation_id: id, user_pool_size: 100, driver_pool_size: 10, target_events_per_second: 50, started_at: Date.now() },
  generator_status: 'RUNNING', generator_error: null, as_of_ms: Date.now(), observed_users: 2,
  metrics: { total_users: 100, active_users: 2, online_drivers: 3, waiting_drivers: 2,
    ride_requests: count, accepted_rides: 1, cancelled_rides: 0, completed_rides: 0 },
  driver_states: { connected: 0, waiting: 2, assigned: 1, offline: 7 },
  ride_history: [{ time_bucket: Math.floor(Date.now() / 60000) * 60000, requested: count, accepted: 1, cancelled: 0, completed: 0 }],
  event_rate: [{ time_bucket: Math.floor(Date.now() / 10000) * 10000, event_count: count, events_per_second: count / 10 }],
});

test('event polling replaces the full run and recovers from failures', async ({ page }) => {
  let mode = 'first';
  await page.route('**/api/v2/dashboard', route => mode === 'failure'
    ? route.fulfill({ status: 503, json: { detail: 'Analytics unavailable' } })
    : route.fulfill({ json: fixture(mode === 'second' ? 'sim-second' : 'sim-first', mode === 'second' ? 1 : 5) }));
  await page.goto('/dashboard-v2');
  await expect(value(page, 'ride_requests')).toHaveText('5');
  await expect(page.locator('.event-card')).toHaveCount(8);
  await expect(page.locator('.event-panel canvas')).toHaveCount(2);
  await expect(page.getByRole('meter')).toHaveCount(4);
  mode = 'failure';
  await expect(page.getByRole('alert')).toContainText('Showing the last successful update');
  await expect(value(page, 'ride_requests')).toHaveText('5');
  mode = 'second';
  await expect(page.getByTestId('run-id')).toHaveText('sim-second');
  await expect(value(page, 'ride_requests')).toHaveText('1');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/dashboard-v2-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-v2-mobile.png', fullPage: true });
});

test('event empty state and navigation cancel polling', async ({ page }) => {
  let requests = 0;
  const data = fixture(); data.run = null; data.generator_status = 'STOPPED'; data.observed_users = 0;
  for (const field of Object.keys(data.metrics)) data.metrics[field] = 0;
  for (const field of Object.keys(data.driver_states)) data.driver_states[field] = 0;
  data.ride_history = []; data.event_rate = [];
  await page.route('**/api/v2/dashboard', route => { requests++; return route.fulfill({ json: data }); });
  await page.goto('/dashboard-v2');
  await expect(page.getByText('No simulation run yet.', { exact: false })).toBeVisible();
  await expect(value(page, 'total_users')).toHaveText('0');
  await page.getByRole('link', { name: 'Generator', exact: true }).click();
  const before = requests;
  await page.waitForTimeout(2500);
  expect(requests).toBe(before);
});

test('live Kafka ingestion populates analytics and a fresh run replaces history', async ({ page, request }) => {
  const initial = await (await request.get('/api/v2/generator/status')).json();
  expect(['STOPPED', 'ERROR']).toContain(initial.status);
  const config = { user_count: 30, driver_count: 5, target_events_per_second: 100 };
  try {
    await page.goto('/dashboard-v2');
    const firstResponse = await request.post('/api/v2/generator/start', { data: config });
    expect(firstResponse.status()).toBe(202);
    const first = await firstResponse.json();
    await expect(page.getByTestId('run-id')).toHaveText(first.simulation_id);
    await expect(value(page, 'total_users')).toHaveText('30');
    await expect.poll(async () => {
      const body = await (await request.get('/api/v2/dashboard')).json();
      return body.event_rate.reduce((sum, row) => sum + row.event_count, 0);
    }, { timeout: 45000 }).toBeGreaterThan(0);
    await expect(page.locator('canvas').first()).toHaveAttribute('aria-label', /Requested [1-9]\d* buckets/, { timeout: 45000 });
    const stopped = await request.post('/api/v2/generator/stop');
    expect(stopped.status()).toBe(200);
    await expect(page.getByText('Run stopped.', { exact: false })).toBeVisible();
    await expect(page.getByTestId('run-id')).toHaveText(first.simulation_id);
    const secondResponse = await request.post('/api/v2/generator/start', { data: { ...config, user_count: 12 } });
    const second = await secondResponse.json();
    expect(second.simulation_id).not.toBe(first.simulation_id);
    await expect(page.getByTestId('run-id')).toHaveText(second.simulation_id);
    await expect(value(page, 'total_users')).toHaveText('12');
    const finalStatus = await (await request.post('/api/v2/generator/stop')).json();
    await expect.poll(async () => {
      const body = await (await request.get('/api/v2/dashboard')).json();
      return body.event_rate.reduce((sum, row) => sum + row.event_count, 0);
    }, { timeout: 45000 }).toBe(finalStatus.published_events);
    const body = await (await request.get('/api/v2/dashboard')).json();
    expect(body.run.simulation_id).toBe(second.simulation_id);
    expect(Object.values(body.driver_states).reduce((a, b) => a + b, 0)).toBe(5);
    expect(body.metrics.active_users).toBe(finalStatus.in_memory.waiting_users + finalStatus.in_memory.users_in_ride);
    expect(body.metrics.waiting_drivers).toBe(finalStatus.in_memory.waiting_drivers);
    expect(body.metrics.online_drivers).toBe(5 - finalStatus.in_memory.offline_drivers);
  } finally { await request.post('/api/v2/generator/stop'); }
});
