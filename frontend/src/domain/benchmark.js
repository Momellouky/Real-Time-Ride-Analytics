export const HISTORY_WINDOW_MS = 600000;
export const MAX_POINTS = 300;
const count = value => Number.isSafeInteger(value) && value >= 0;
const number = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
export function validateBenchmark(data) {
  const fail = () => { throw new Error('The service returned invalid benchmark measurements. Please retry.'); };
  if (!data || !count(data.as_of_ms) || (data.simulation_id !== null &&
    (typeof data.simulation_id !== 'string' || !data.simulation_id))) fail();
  const g = data.generator, p = data.pinot, s = data.system;
  if (!g || !['STOPPED', 'WARMING_UP', 'RUNNING', 'STOPPING', 'ERROR'].includes(g.status) ||
    !['target_events_per_second', 'generated_events', 'published_events'].every(f => count(g[f])) ||
    !number(g.actual_events_per_second) || !(g.last_error === null || typeof g.last_error === 'string')) fail();
  if (!p || !count(p.total_ingested_events) || !count(p.events_not_yet_visible) ||
    p.events_not_yet_visible !== Math.max(0, g.generated_events - p.total_ingested_events)) fail();
  if (p.total_ingested_events === 0) {
    if (p.latest_event_timestamp !== null || p.ingestion_lag_ms !== null) fail();
  } else if (!count(p.latest_event_timestamp) || p.latest_event_timestamp > data.as_of_ms || !count(p.ingestion_lag_ms)) fail();
  const latency = p.query_latency;
  if (!latency || !['avg_ms', 'p95_ms', 'p99_ms'].every(f => number(latency[f])) ||
    !count(latency.sample_count) || latency.sample_count > 500 || latency.p99_ms < latency.p95_ms) fail();
  if (s !== null && (!s || s.scope !== 'os_visible_to_backend' || !count(s.sampled_at_ms) ||
    !(s.cpu_percent === null || (number(s.cpu_percent) && s.cpu_percent <= 100)) ||
    !number(s.memory_percent) || s.memory_percent > 100 || !number(s.memory_used_gb) ||
    !number(s.memory_total_gb) || s.memory_total_gb === 0)) fail();
  if (data.simulation_id === null && (p.total_ingested_events !== 0 || g.generated_events !== 0)) fail();
  return data;
}

export function appendBenchmarkHistory(history, previousRunId, data, timestamp) {
  const kept = previousRunId === data.simulation_id
    ? history.filter(row => row.timestamp > timestamp - HISTORY_WINDOW_MS && row.timestamp < timestamp) : [];
  return [...kept, { timestamp, actualEps: data.generator.actual_events_per_second,
    avgLatency: data.pinot.query_latency.sample_count ? data.pinot.query_latency.avg_ms : null,
    p95Latency: data.pinot.query_latency.sample_count ? data.pinot.query_latency.p95_ms : null,
    p99Latency: data.pinot.query_latency.sample_count ? data.pinot.query_latency.p99_ms : null,
    ingestionLag: data.pinot.ingestion_lag_ms === null ? null : data.pinot.ingestion_lag_ms / 1000,
    systemTimestamp: data.system?.sampled_at_ms ?? null,
    cpu: data.system?.cpu_percent ?? null, memory: data.system?.memory_percent ?? null,
  }].slice(-MAX_POINTS);
}
