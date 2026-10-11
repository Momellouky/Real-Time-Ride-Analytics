import { test, expect } from '@playwright/test';

const idle = { simulation_id: null, status: 'STOPPED', target_events_per_second: 0,
  actual_events_per_second: 0, generated_events: 0, published_events: 0,
  user_pool_size: 0, driver_pool_size: 0, in_memory: { idle_users: 0, waiting_users: 0,
    users_in_ride: 0, offline_drivers: 0, waiting_drivers: 0, assigned_drivers: 0 }, last_error: null };
const running = { ...idle, simulation_id: 'sim-browser', status: 'RUNNING', target_events_per_second: 250,
  user_pool_size: 10000, driver_pool_size: 2000, generated_events: 100, published_events: 100 };

test('controls real fresh runs, survives reload/navigation, and retains final statistics', async ({ page, request }) => {
  const initial = await (await request.get('/api/v2/generator/status')).json();
  expect(initial.status).toBe('STOPPED');
  const before = await (await request.get('/api/metrics/current')).json();
  const runs = [];
  try {
    await page.goto('/generator');
    await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeEnabled();
    await page.getByLabel('User pool', { exact: true }).fill('30');
    await page.getByLabel('Driver pool', { exact: true }).fill('5');
    await page.getByRole('radio', { name: '50 events/s', exact: true }).check();
    const startResponse = page.waitForResponse((r) => r.url().endsWith('/api/v2/generator/start') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Start Generator', exact: true }).click();
    const response = await startResponse;
    expect(response.status()).toBe(202);
    expect(response.request().postDataJSON()).toEqual({ user_count: 30, driver_count: 5, target_events_per_second: 50 });
    const first = await response.json();
    await expect(page.getByTestId('generator-state')).toHaveText('RUNNING');
    await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeDisabled();
    await expect(page.getByLabel('User pool', { exact: true })).toBeDisabled();
    await expect.poll(async () => Number((await page.getByTestId('generated-events').textContent()).replaceAll(',', ''))).toBeGreaterThan(0);
    const countBeforePoll = Number((await page.getByTestId('generated-events').textContent()).replaceAll(',', ''));
    await expect.poll(async () => Number((await page.getByTestId('generated-events').textContent()).replaceAll(',', '')),
      { timeout: 10000 }).toBeGreaterThan(countBeforePoll);
    await page.reload();
    await expect(page.getByTestId('simulation-id')).toHaveText(first.simulation_id);
    await expect(page.getByLabel('User pool', { exact: true })).toHaveValue('30');
    await page.getByRole('link', { name: 'Metrics Settings', exact: true }).click();
    expect((await (await request.get('/api/v2/generator/status')).json()).simulation_id).toBe(first.simulation_id);
    await page.getByRole('link', { name: 'Generator', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Stop Generator', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Stop Generator', exact: true }).click();
    await expect(page.getByTestId('generator-state')).toHaveText('STOPPED');
    const stopped = await (await request.get('/api/v2/generator/status')).json();
    runs.push(stopped);
    expect(stopped.generated_events).toBe(stopped.published_events);
    expect(stopped.generated_events).toBeGreaterThan(0);
    await expect(page.getByTestId('generated-events')).toHaveText(stopped.generated_events.toLocaleString('en-US'));
    await page.screenshot({ path: 'test-results/generator-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: 'test-results/generator-mobile.png', fullPage: true });
    await page.getByRole('button', { name: 'Start Generator', exact: true }).click();
    await expect(page.getByTestId('simulation-id')).not.toHaveText(first.simulation_id);
    await expect(page.getByRole('button', { name: 'Stop Generator', exact: true })).toBeEnabled();
    await expect.poll(async () => (await (await request.get('/api/v2/generator/status')).json()).generated_events).toBeGreaterThan(0);
    await page.getByRole('button', { name: 'Stop Generator', exact: true }).click();
    await expect(page.getByTestId('generator-state')).toHaveText('STOPPED');
    runs.push(await (await request.get('/api/v2/generator/status')).json());
    for (const run of runs) {
      expect(run.generated_events).toBe(run.published_events);
      await expect.poll(async () => {
        const result = await request.post('http://pinot-broker:8099/query/sql', { data: {
          sql: `SELECT COUNT(*) AS total, DISTINCTCOUNT(event_id) AS unique_events FROM operations WHERE simulation_id = '${run.simulation_id}'` } });
        const data = await result.json();
        expect(data.exceptions || []).toHaveLength(0);
        return data.resultTable?.rows;
      }, { timeout: 45000 }).toEqual([[run.published_events, run.published_events]]);
    }
    console.log('Verified browser runs:', JSON.stringify(runs));
    expect(await (await request.get('/api/metrics/current')).json()).toEqual(before);
  } finally {
    const stop = await request.post('/api/v2/generator/stop');
    expect(stop.ok()).toBeTruthy();
  }
});

test('validates pool sizes and custom rates, with a non-blocking high-rate warning', async ({ page }) => {
  await page.route('**/api/v2/generator/status', (route) => route.fulfill({ json: idle }));
  let starts = 0;
  await page.route('**/api/v2/generator/start', (route) => { starts++; return route.fulfill({ status: 503, json: { detail: 'Broker unavailable.' } }); });
  await page.goto('/generator');
  const start = page.getByRole('button', { name: 'Start Generator', exact: true });
  await expect(start).toBeEnabled();
  await page.getByLabel('User pool', { exact: true }).fill('0');
  await expect(start).toBeDisabled();
  await page.getByLabel('User pool', { exact: true }).fill('30');
  await page.getByLabel('Driver pool', { exact: true }).fill('1.5');
  await expect(start).toBeDisabled();
  await page.getByLabel('Driver pool', { exact: true }).fill('5');
  await page.getByRole('radio', { name: 'Custom', exact: true }).check();
  await page.getByLabel('Custom events per second').fill('');
  await expect(start).toBeDisabled();
  expect(starts).toBe(0);
  await page.getByLabel('Custom events per second').fill('1250');
  await expect(page.getByRole('status')).toContainText('above 1,000');
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByRole('alert')).toContainText('Broker unavailable');
  await expect(page.getByLabel('User pool', { exact: true })).toHaveValue('30');
  expect(starts).toBe(1);
});

test('status failures disable Start and retry recovers, then polling stops on navigation', async ({ page }) => {
  let reads = 0;
  await page.route('**/api/v2/generator/status', (route) => {
    reads++;
    return reads === 1 ? route.fulfill({ status: 503, json: { detail: 'Status unavailable.' } }) : route.fulfill({ json: idle });
  });
  await page.goto('/generator');
  await expect(page.getByRole('alert')).toContainText('Status unavailable');
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Retry status' }).click();
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeEnabled();
  await page.getByRole('link', { name: 'Dashboard', exact: true }).click();
  const count = reads;
  await page.waitForTimeout(2200);
  expect(reads).toBe(count);
});

test('a Start conflict reconciles an already-running simulation', async ({ page }) => {
  let active = false;
  await page.route('**/api/v2/generator/status', (route) => route.fulfill({ json: active ? running : idle }));
  await page.route('**/api/v2/generator/start', (route) => {
    active = true; return route.fulfill({ status: 409, json: { detail: 'Generator is already active.' } });
  });
  await page.goto('/generator');
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start Generator', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('already active');
  await expect(page.getByTestId('generator-state')).toHaveText('RUNNING');
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Stop Generator', exact: true })).toBeEnabled();
});

test('STOPPING disables controls and failed drains remain visible', async ({ page }) => {
  let state = { ...running, status: 'STOPPING' };
  await page.route('**/api/v2/generator/status', (route) => route.fulfill({ json: state }));
  await page.goto('/generator');
  await expect(page.getByTestId('generator-state')).toHaveText('STOPPING');
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Stop Generator', exact: true })).toBeDisabled();
  state = { ...running, status: 'ERROR', last_error: 'Unable to drain operations producer' };
  await expect(page.getByRole('alert')).toContainText('Unable to drain');
  await expect(page.getByTestId('generated-events')).toHaveText('100');
  await expect(page.getByRole('button', { name: 'Start Generator', exact: true })).toBeEnabled();
});
