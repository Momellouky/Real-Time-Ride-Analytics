import { expect, it } from 'vitest';
import { appendBenchmarkHistory, validateBenchmark, MAX_POINTS, HISTORY_WINDOW_MS } from '../src/domain/benchmark.js';

const fixture = () => ({ simulation_id: 'sim-one', as_of_ms: 5000000,
  generator: { status: 'RUNNING', target_events_per_second: 250, actual_events_per_second: 249.5,
    generated_events: 100, published_events: 95, last_error: null },
  pinot: { total_ingested_events: 90, events_not_yet_visible: 10, latest_event_timestamp: 4999900,
    ingestion_lag_ms: 100, query_latency: { avg_ms: 20, p95_ms: 30, p99_ms: 40, sample_count: 100 } },
  system: { sampled_at_ms: 4999900, cpu_percent: 10, memory_percent: 50, memory_used_gb: 8,
    memory_total_gb: 16, scope: 'os_visible_to_backend' } });

it('validates API measurements without changing them', () => {
  const data = fixture(); expect(validateBenchmark(data)).toBe(data);
});
it.each(['simulation_id', 'generator', 'pinot', 'system', 'as_of_ms'])('rejects missing %s', field => {
  const data = fixture(); delete data[field]; expect(() => validateBenchmark(data)).toThrow();
});
it.each([-1, NaN, Infinity, '25'])('rejects invalid rates %s', value => {
  const data = fixture(); data.generator.actual_events_per_second = value;
  expect(() => validateBenchmark(data)).toThrow();
});
it('accepts missing system data and CPU priming', () => {
  const data = fixture(); data.system.cpu_percent = null; validateBenchmark(data);
  data.system = null; validateBenchmark(data);
});
it('rejects impossible percentages and latency windows', () => {
  const data = fixture(); data.system.cpu_percent = 101; expect(() => validateBenchmark(data)).toThrow();
  data.system.cpu_percent = 10; data.pinot.query_latency.sample_count = 501;
  expect(() => validateBenchmark(data)).toThrow();
});
it('rejects mismatched backlog and future event timestamp', () => {
  const data = fixture(); data.pinot.events_not_yet_visible = 9; expect(() => validateBenchmark(data)).toThrow();
  data.pinot.events_not_yet_visible = 10; data.pinot.latest_event_timestamp = 5000001;
  expect(() => validateBenchmark(data)).toThrow();
});
it('requires unknown freshness for an empty run', () => {
  const data = fixture(); Object.assign(data.pinot, { total_ingested_events: 0, events_not_yet_visible: 100 });
  expect(() => validateBenchmark(data)).toThrow();
  Object.assign(data.pinot, { latest_event_timestamp: null, ingestion_lag_ms: null });
  validateBenchmark(data);
});
it('retains at most 300 samples under fast polling', () => {
  const data = fixture(); let history = [];
  for (let i = 0; i < 1000; i++) history = appendBenchmarkHistory(history, data.simulation_id, data, 5000000 + i);
  expect(history).toHaveLength(MAX_POINTS);
  expect(history[0].timestamp).toBe(5000700);
});
it('expires samples by time even when there are fewer than 300', () => {
  const data = fixture(); const now = 5000000;
  const history = appendBenchmarkHistory([{ timestamp: now - HISTORY_WINDOW_MS }, { timestamp: now - 1000 }],
    data.simulation_id, data, now);
  expect(history.map(row => row.timestamp)).toEqual([now - 1000, now]);
});
it.each(['sim-two', null])('clears history when switching to %s', id => {
  const data = fixture(); data.simulation_id = id;
  expect(appendBenchmarkHistory([{ timestamp: 4999900 }], 'sim-one', data, 5000000)).toHaveLength(1);
});
it('preserves nullable measurements and converts freshness to seconds', () => {
  const data = fixture(); data.system = null; data.pinot.query_latency.sample_count = 0;
  const [row] = appendBenchmarkHistory([], null, data, 5000000);
  expect(row.cpu).toBeNull(); expect(row.memory).toBeNull(); expect(row.avgLatency).toBeNull();
  expect(row.ingestionLag).toBe(.1);
});
it('does not mutate previous history and handles a clock regression', () => {
  const data = fixture(), previous = [{ timestamp: 5000001 }];
  expect(appendBenchmarkHistory(previous, data.simulation_id, data, 5000000)).toHaveLength(1);
  expect(previous).toEqual([{ timestamp: 5000001 }]);
});
