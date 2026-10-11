<script setup>
import { computed } from 'vue';
import { useDashboardV2 } from '../composables/useDashboardV2.js';
import { CARDS } from '../domain/dashboard-v2.js';
import EventSeriesChart from '../components/EventSeriesChart.vue';
const { data, error, refreshing, updatedAt, interval, refresh } = useDashboardV2();
const lifecycle = computed(() => ['requested', 'accepted', 'cancelled', 'completed'].map((field, i) => ({
  label: field[0].toUpperCase() + field.slice(1), color: ['#4a6bb5', '#126354', '#b77345', '#50863e'][i],
  points: data.value.ride_history.map(row => ({ x: row.time_bucket, y: row[field] })),
})));
const rate = computed(() => [{ label: 'Ingested events / second', color: '#126354',
  points: data.value.event_rate.map(row => ({ x: row.time_bucket, y: row.events_per_second })) }]);
const driverLabels = { waiting: 'Waiting', assigned: 'Assigned', connected: 'Connected', offline: 'Offline' };
</script>
<template>
  <div class="dashboard-heading">
    <div class="page-heading"><p class="eyebrow">OPERATIONS / ZONE 1</p><h1>Event Analytics Dashboard</h1>
      <p class="page-description">Ride activity and fleet availability, measured from ingested operational events.</p></div>
    <RouterLink to="/generator" class="button primary">Manage generator ↗</RouterLink>
  </div>
  <div class="dashboard-status"><span class="refresh-status" :class="{ reconnecting: error }">{{ error ? 'Reconnecting' : `Auto-refresh · every ${interval / 1000}s` }}</span>
    <span v-if="updatedAt">Updated {{ new Date(updatedAt).toLocaleTimeString() }}</span></div>
  <div v-if="error" class="notice error-notice dashboard-notice" role="alert">
    <div><strong>Unable to refresh analytics.</strong> {{ error }}<p v-if="data">Showing the last successful update.</p></div>
    <button class="button secondary" :disabled="refreshing" @click="refresh">Retry now</button>
  </div>
  <p v-if="!data && !error" role="status">Loading event analytics…</p>
  <template v-if="data">
    <section class="event-run" aria-label="Simulation run">
      <template v-if="data.run"><strong>{{ data.generator_status }}</strong><code data-testid="run-id">{{ data.run.simulation_id }}</code>
        <span>{{ data.run.user_pool_size.toLocaleString() }} users · {{ data.run.driver_pool_size.toLocaleString() }} drivers · Target {{ data.run.target_events_per_second.toLocaleString() }} events/s</span>
        <small>Started {{ new Date(data.run.started_at).toLocaleString() }} · {{ data.observed_users.toLocaleString() }} users observed</small>
        <p v-if="data.generator_status === 'STOPPED'">Run stopped. Fleet state is retained; activity windows continue to roll forward.</p>
        <p v-if="data.generator_error" role="alert">Generator error: {{ data.generator_error }}</p>
      </template>
      <p v-else role="status">No simulation run yet. Start a run from Generator to populate event analytics.</p>
    </section>
    <div class="event-metrics">
      <section v-for="[field, label, description] in CARDS" :key="field" class="event-card" :data-metric="field">
        <h2>{{ label }}</h2><p class="metric-value">{{ data.metrics[field].toLocaleString() }}</p><small>{{ description }}</small>
      </section>
    </div>
    <section class="event-panel"><h2>Ride lifecycle</h2><p>Last hour · events per minute</p>
      <EventSeriesChart label="Ride lifecycle" :series="lifecycle" :window-end="data.as_of_ms" :duration="3600000" :bucket-width="60000" />
    </section>
    <div class="event-bottom">
      <section class="event-panel"><h2>Pinot-ingested event rate</h2><p>Last 10 minutes · 10-second buckets. Open buckets are partial.</p>
        <EventSeriesChart label="Event rate" :series="rate" :window-end="data.as_of_ms" :duration="600000" :bucket-width="10000" />
      </section>
      <section class="event-panel"><h2>Driver distribution</h2><p>Latest known state · includes drivers that have never connected</p>
        <div v-for="(label, state) in driverLabels" :key="state" class="driver-bar-row">
          <span>{{ label }}</span><strong>{{ data.driver_states[state].toLocaleString() }}</strong>
          <meter :aria-label="`${label} drivers`" min="0" :max="Math.max(1, data.run?.driver_pool_size || 0)" :value="data.driver_states[state]" />
        </div>
      </section>
    </div>
  </template>
</template>
