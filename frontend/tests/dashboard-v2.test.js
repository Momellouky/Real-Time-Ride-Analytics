import { describe, expect, it } from 'vitest';
import { CARDS, validateDashboardV2 } from '../src/domain/dashboard-v2.js';

const fixture = () => ({ run: { simulation_id: 'sim-one', user_pool_size: 100, driver_pool_size: 10,
  target_events_per_second: 250, started_at: 1000 }, generator_status: 'STOPPED', as_of_ms: 3600000,
  metrics: Object.fromEntries(CARDS.map(([f]) => [f, f === 'total_users' ? 100 : f === 'online_drivers' ? 3 : f === 'waiting_drivers' ? 2 : 0])),
  driver_states: { connected: 1, waiting: 2, assigned: 0, offline: 7 }, observed_users: 0,
  ride_history: [{ time_bucket: 3540000, requested: 1, accepted: 0, cancelled: 0, completed: 0 }],
  event_rate: [{ time_bucket: 3590000, event_count: 3, events_per_second: 0.3 }] });

describe('event dashboard validation', () => {
  it('accepts a stopped run with historical data', () => { const data = fixture(); expect(validateDashboardV2(data)).toBe(data); });
  it.each(['metrics', 'driver_states', 'ride_history', 'event_rate', 'run', 'as_of_ms', 'generator_status'])('rejects missing %s', field => {
    const data = fixture(); delete data[field]; expect(() => validateDashboardV2(data)).toThrow();
  });
  it.each([-1, 1.5, '2', NaN])('rejects invalid counts %s', value => {
    const data = fixture(); data.metrics.active_users = value; expect(() => validateDashboardV2(data)).toThrow();
  });
  it('rejects inconsistent fleet totals', () => { const data = fixture(); data.driver_states.offline = 9; expect(() => validateDashboardV2(data)).toThrow(); });
  it('rejects stale buckets and mismatched rates', () => {
    const data = fixture(); data.event_rate[0].events_per_second = 3; expect(() => validateDashboardV2(data)).toThrow();
    data.event_rate[0].events_per_second = 0.3; data.event_rate[0].time_bucket = 10000; expect(() => validateDashboardV2(data)).toThrow();
  });
  it('rejects duplicate history buckets', () => { const data = fixture(); data.ride_history.push(data.ride_history[0]); expect(() => validateDashboardV2(data)).toThrow(); });
});
