import { test, expect } from '@playwright/test';

const fields = ['online_drivers', 'ride_requests', 'accepted_requests', 'cancelled_requests', 'waiting_drivers'];
const base = { zone_id: 'ZONE_1', event_id: 'first', event_timestamp: Date.now(),
  online_drivers: 75, ride_requests: 100, accepted_requests: 60, cancelled_requests: 15, waiting_drivers: 20 };
const point = (snapshot) => Object.fromEntries(['event_timestamp', ...fields].map((f) => [f, snapshot[f]]));
const value = (page, field) => page.locator(`[data-metric="${field}"] .metric-value`);

test('Settings submission updates all dashboard cards and charts without reloading', async ({ page, context, request }) => {
  const failures = [];
  page.on('pageerror', (e) => failures.push(e.message));
  await page.goto('/');
  await expect(page.locator('.metric-card')).toHaveCount(5);
  await expect(page.locator('canvas')).toHaveCount(5);
  const settings = await context.newPage();
  await settings.goto('/settings');
  await expect(settings.getByRole('button', { name: 'Publish snapshot' })).toBeEnabled();
  const original = {};
  for (const field of fields) original[field] = Number(await settings.locator(`#${field}`).inputValue());
  const next = original.online_drivers + 1;
  await settings.locator('#online_drivers').fill(String(next));
  const ack = settings.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/metrics'));
  await settings.getByRole('button', { name: 'Publish snapshot' }).click();
  const acceptedResponse = await ack;
  expect(acceptedResponse.status()).toBe(202);
  const accepted = await acceptedResponse.json();
  await expect(value(page, 'online_drivers')).toHaveText(next.toLocaleString(), { timeout: 45000 });
  for (const field of fields) {
    const expected = field === 'online_drivers' ? next : original[field];
    await expect(value(page, field)).toHaveText(expected.toLocaleString());
    await expect(page.locator(`[data-metric="${field}"] canvas`)).toHaveAttribute('aria-label', new RegExp(`latest observation ${expected}$`));
  }
  const dashboard = await (await request.get('/api/dashboard')).json();
  expect(dashboard.current.event_id).toBe(accepted.event_id);
  expect(dashboard.history.some((row) => row.event_timestamp === accepted.event_timestamp)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
  expect(failures).toEqual([]);
  await settings.close();
});

test('refresh errors preserve data and later polling recovers', async ({ page }) => {
  let mode = 'success';
  await page.route('**/api/dashboard*', (route) => {
    if (mode === 'failure') return route.fulfill({ status: 503, json: { detail: 'Analytics are temporarily unavailable.' } });
    const current = mode === 'recovered' ? { ...base, online_drivers: 90 } : base;
    return route.fulfill({ json: { current, history: [point(current)] } });
  });
  await page.goto('/');
  await expect(value(page, 'online_drivers')).toHaveText('75');
  mode = 'failure';
  await expect(page.getByRole('alert')).toContainText('Showing the last successful update');
  await expect(value(page, 'online_drivers')).toHaveText('75');
  mode = 'recovered';
  await expect(value(page, 'online_drivers')).toHaveText('90');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('zero state renders empty charts and polling stops when leaving Dashboard', async ({ page }) => {
  let requests = 0;
  const zero = Object.fromEntries(fields.map((f) => [f, 0]));
  await page.route('**/api/dashboard*', (route) => {
    requests++;
    return route.fulfill({ json: { current: { zone_id: 'ZONE_1', event_id: null, event_timestamp: null, ...zero }, history: [] } });
  });
  await page.route('**/api/metrics/current*', (route) => route.fulfill({ json: base }));
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('No snapshots yet');
  await expect(page.locator('.chart-empty')).toHaveCount(5);
  for (const field of fields) await expect(value(page, field)).toHaveText('0');
  await page.getByRole('link', { name: 'Metrics Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Metrics Settings', exact: true })).toBeVisible();
  const stoppedAt = requests;
  await page.waitForTimeout(2500);
  expect(requests).toBe(stoppedAt);
});

test('initial failure shows a retry and old current state can have empty history', async ({ page }) => {
  let fail = true;
  await page.route('**/api/dashboard*', (route) => route.fulfill(fail
    ? { status: 503, json: { detail: 'Analytics unavailable.' } }
    : { json: { current: { ...base, event_timestamp: Date.now() - 7200000 }, history: [] } }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('Unable to refresh');
  fail = false;
  await page.getByRole('button', { name: 'Retry now' }).click();
  await expect(value(page, 'online_drivers')).toHaveText('75');
  await expect(page.locator('.chart-empty')).toHaveCount(5);
  await expect(page.getByRole('alert')).toHaveCount(0);
});
