import { test, expect } from '@playwright/test';

const fields = ['online_drivers', 'ride_requests', 'accepted_requests', 'cancelled_requests', 'waiting_drivers'];
const initial = { zone_id: 'ZONE_1', event_id: 'old', event_timestamp: 1000,
  online_drivers: 75, ride_requests: 100, accepted_requests: 60, cancelled_requests: 15, waiting_drivers: 20 };

test('loads real Pinot data, publishes one changed metric, and reloads persisted values', async ({ page, request }) => {
  const before = await request.get('/api/metrics/current?zone_id=ZONE_1');
  expect(before.ok()).toBeTruthy();
  const snapshot = await before.json();
  await page.goto('/settings');
  for (const field of fields) await expect(page.locator(`#${field}`)).toHaveValue(String(snapshot[field]));
  await page.locator('#accepted_requests').fill(String(snapshot.ride_requests + 1));
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeDisabled();
  await expect(page.locator('#accepted_requests-error')).toContainText('must not exceed');
  await page.locator('#accepted_requests').fill(String(snapshot.accepted_requests));
  const updated = snapshot.online_drivers + 1;
  await page.locator('#online_drivers').fill(String(updated));
  const sent = page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/metrics'));
  const ack = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/api/metrics'));
  await page.getByRole('button', { name: 'Publish snapshot' }).click();
  const payload = (await sent).postDataJSON();
  expect(payload).toEqual({ zone_id: 'ZONE_1', ...Object.fromEntries(fields.map((f) => [f, f === 'online_drivers' ? updated : snapshot[f]])) });
  const response = await ack;
  expect(response.status()).toBe(202);
  const accepted = await response.json();
  await expect(page.getByRole('status')).toContainText('Snapshot published.');
  await expect.poll(async () => (await (await request.get('/api/metrics/current')).json()).event_id,
    { timeout: 45000 }).toBe(accepted.event_id);
  await page.reload();
  for (const field of fields) await expect(page.locator(`#${field}`)).toHaveValue(String(payload[field]));
  await page.screenshot({ path: 'test-results/settings-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/settings-mobile.png', fullPage: true });
});

test('load failures disable the form and offer retry', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/metrics/current*', (route) => {
    attempts++;
    return route.fulfill({ status: attempts === 1 ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify(attempts === 1 ? { detail: 'Analytics are temporarily unavailable.' } : initial) });
  });
  await page.goto('/settings');
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable');
  await expect(page.locator('#online_drivers')).toBeDisabled();
  await page.getByRole('button', { name: 'Retry loading' }).click();
  await expect(page.locator('#online_drivers')).toHaveValue('75');
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeEnabled();
});

test('blank inputs block submission and publish failures preserve edits', async ({ page }) => {
  await page.route('**/api/metrics/current*', (route) => route.fulfill({ json: initial }));
  await page.route('**/api/metrics', (route) => route.fulfill({ status: 503, json: { detail: 'Unable to publish metrics event to Kafka.' } }));
  await page.goto('/settings');
  await expect(page.locator('#online_drivers')).toHaveValue('75');
  await page.locator('#online_drivers').fill('');
  await expect(page.locator('#online_drivers')).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeDisabled();
  await page.locator('#online_drivers').fill('90');
  await page.getByRole('button', { name: 'Publish snapshot' }).click();
  await expect(page.getByRole('alert')).toContainText('Unable to publish');
  await expect(page.locator('#online_drivers')).toHaveValue('90');
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeEnabled();
});

test('negative values and waiting-driver violations do not send requests', async ({ page }) => {
  let published = 0;
  await page.route('**/api/metrics/current*', (route) => route.fulfill({ json: initial }));
  await page.route('**/api/metrics', (route) => {
    published++;
    return route.fulfill({ status: 202, json: { status: 'accepted', event_id: 'unexpected', event_timestamp: 1 } });
  });
  await page.goto('/settings');
  await expect(page.locator('#online_drivers')).toHaveValue('75');
  await page.locator('#online_drivers').fill('-1');
  await expect(page.locator('#online_drivers-error')).toContainText('whole number');
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeDisabled();
  await page.locator('#online_drivers').fill('75');
  await page.locator('#waiting_drivers').fill('76');
  await expect(page.locator('#waiting_drivers-error')).toContainText('must not exceed');
  await expect(page.getByRole('button', { name: 'Publish snapshot' })).toBeDisabled();
  await page.locator('#waiting_drivers').press('Enter');
  expect(published).toBe(0);
});
