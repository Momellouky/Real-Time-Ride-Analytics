<script setup>
import { computed } from 'vue';
import { useBenchmark } from '../composables/useBenchmark.js';
import { HISTORY_WINDOW_MS } from '../domain/benchmark.js';
import EventSeriesChart from './EventSeriesChart.vue';

const { data, history, error, refreshing, updatedAt, refresh } = useBenchmark();
const format = (value, digits = 1) => value === null || value === undefined ? '—'
  : value.toLocaleString(undefined, { maximumFractionDigits: digits });
const cards = computed(() => {
  const { generator: g, pinot: p, system: s } = data.value;
  const latency = p.query_latency.sample_count > 0;
  return [
    ['target', 'Target EPS', format(g.target_events_per_second), 'Configured events / second'],
    ['actual', 'Actual EPS', format(g.actual_events_per_second), g.status === 'STOPPED' || g.status === 'ERROR' ? 'Final acknowledged rate' : 'Acknowledged events / second'],
    ['ingested', 'Ingested events', format(p.total_ingested_events, 0), `${format(p.events_not_yet_visible, 0)} generated events not yet visible`],
    ['avg', 'Pinot average', latency ? `${format(p.query_latency.avg_ms)} ms` : '—', 'Recent individual query latency'],
    ['p95', 'Pinot p95', latency ? `${format(p.query_latency.p95_ms)} ms` : '—', '95th percentile query latency'],
    ['p99', 'Pinot p99', latency ? `${format(p.query_latency.p99_ms)} ms` : '—', '99th percentile query latency'],
    ['lag', 'Ingestion freshness', p.ingestion_lag_ms === null ? '—' : `${format(p.ingestion_lag_ms / 1000)} s`, p.latest_event_timestamp === null ? 'No events visible yet' : 'Age of newest visible event'],
    ['cpu', 'CPU usage', s?.cpu_percent === null || !s ? '—' : `${format(s.cpu_percent)}%`, s ? 'Operating system visible to backend' : 'System sample unavailable'],
    ['memory', 'Memory usage', s ? `${format(s.memory_used_gb, 2)} / ${format(s.memory_total_gb, 2)} GiB` : '—', s ? `${format(s.memory_percent)}% · OS-visible memory` : 'System sample unavailable'],
  ];
});
const charts = [
  { label: 'Actual EPS over time', unit: 'Events / second', fields: [['actualEps', 'Acknowledged EPS', '#126354']] },
  { label: 'Pinot query latency over time', unit: 'Milliseconds', fields: [['avgLatency', 'Average', '#126354'], ['p95Latency', 'p95', '#4a6bb5'], ['p99Latency', 'p99', '#b77345']] },
  { label: 'Ingestion freshness over time', unit: 'Seconds', fields: [['ingestionLag', 'Newest event age', '#b77345']] },
  { label: 'CPU usage over time', unit: 'Percent', max: 100, system: true, fields: [['cpu', 'CPU', '#4a6bb5']] },
  { label: 'Memory usage over time', unit: 'Percent', max: 100, system: true, fields: [['memory', 'Memory', '#707b45']] },
];
function series(chart) {
  return chart.fields.map(([field, label, color]) => {
    let previous = null;
    const points = [];
    for (const row of history.value) {
      const x = chart.system ? row.systemTimestamp : row.timestamp;
      if (x === null || (previous !== null && x <= previous) || x < updatedAt.value - HISTORY_WINDOW_MS || x > updatedAt.value) continue;
      previous = x;
      points.push({ x, y: row[field] });
    }
    return { label, color, points };
  });
}
</script>

<template>
  <section class="benchmark-panel" aria-labelledby="benchmark-heading">
    <div class="dashboard-heading">
      <div><p class="eyebrow">RUNTIME PERFORMANCE</p><h2 id="benchmark-heading">Benchmark &amp; Observability</h2>
        <p class="page-description">Load, query latency, ingestion freshness, and system resource usage.</p></div>
      <span class="refresh-status">{{ error ? 'Reconnecting' : 'Auto-refresh · every 2s' }}</span>
    </div>
    <div v-if="error" class="notice error-notice dashboard-notice" role="alert">
      <div><strong>Unable to refresh observability.</strong> {{ error }}
        <p v-if="data">Showing the last successful update from {{ new Date(updatedAt).toLocaleTimeString() }}.</p></div>
      <button class="button secondary" :disabled="refreshing" @click="refresh">Retry observability</button>
    </div>
    <p v-if="!data && !error" role="status">Loading runtime measurements…</p>
    <template v-if="data">
      <div class="benchmark-context">
        <strong>{{ data.generator.status }}</strong><code data-testid="benchmark-run-id">{{ data.simulation_id || 'No simulation run' }}</code>
        <span>{{ format(data.generator.generated_events, 0) }} generated · {{ format(data.generator.published_events, 0) }} acknowledged</span>
        <span>{{ data.pinot.query_latency.sample_count }} recent query samples · {{ history.length }} browser observations</span>
        <span v-if="data.system">System sampled {{ new Date(data.system.sampled_at_ms).toLocaleTimeString() }}</span>
      </div>
      <p v-if="!data.simulation_id" class="benchmark-note">Start a generator run to measure event throughput and ingestion freshness. System measurements remain available.</p>
      <p v-if="['STOPPED', 'ERROR'].includes(data.generator.status) && data.simulation_id" class="benchmark-note">
        Production has stopped. Actual EPS is the final reported rate; newest-event age grows even after ingestion catches up.
      </p>
      <p v-if="data.generator.last_error" class="benchmark-note" role="alert">Generator error: {{ data.generator.last_error }}</p>
      <div class="benchmark-cards">
        <section v-for="[field, label, value, description] in cards" :key="field" class="benchmark-card" :data-benchmark="field">
          <h3>{{ label }}</h3><p class="benchmark-value">{{ value }}</p><small>{{ description }}</small>
        </section>
      </div>
      <p class="benchmark-note">Query timings include all shared-client queries, including this page and snapshot analytics, over the latest 500 samples.
        Resource usage reflects the backend's visible operating system, which may be the host or Docker VM.</p>
      <div class="benchmark-charts">
        <section v-for="chart in charts" :key="chart.label" class="benchmark-chart">
          <h3>{{ chart.label }}</h3><p>Last 10 minutes · collected while this page is open</p>
          <EventSeriesChart :label="chart.label" :series="series(chart)" :window-end="updatedAt" :duration="HISTORY_WINDOW_MS"
            :bucket-width="1" :unit="chart.unit" :y-max="chart.max" :integer-ticks="false" point-label="samples"
            empty-message="No measurements available in this window" />
        </section>
      </div>
    </template>
  </section>
</template>
