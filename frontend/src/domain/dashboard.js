import { METRICS } from './metrics.js';

export const HOUR_MS = 3600000;

export function pollingInterval(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 250 && parsed <= 2147483647 ? parsed : 2000;
}

export function toSeries(history, field) {
  return history.map((row) => ({ x: row.event_timestamp, y: row[field] }));
}

export function validateDashboard(payload) {
  const isMetrics = (row) => row && METRICS.every(({ field }) =>
    Number.isInteger(row[field]) && row[field] >= 0);
  if (!isMetrics(payload?.current) || payload.current.zone_id !== 'ZONE_1' ||
      !Array.isArray(payload.history) || !payload.history.every((row) =>
        isMetrics(row) && Number.isInteger(row.event_timestamp) && row.event_timestamp >= 0) ||
      payload.history.some((row, i) => i > 0 && row.event_timestamp < payload.history[i - 1].event_timestamp)) {
    throw new Error('The service returned invalid dashboard data. Retrying automatically.');
  }
  return payload;
}
