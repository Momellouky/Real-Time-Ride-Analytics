<script setup>
import { computed } from 'vue';
import { useDashboard } from '../composables/useDashboard.js';
import { METRICS } from '../domain/metrics.js';
import MetricCard from '../components/MetricCard.vue';

const { data, error, refreshing, updatedAt, interval, refresh } = useDashboard();
const colors = ['#126354', '#4a6bb5', '#50863e', '#b77345', '#707b45'];
const snapshotTime = computed(() => data.value?.current.event_timestamp
  ? new Date(data.value.current.event_timestamp).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
  : 'No snapshots yet');
</script>

<template>
  <div class="dashboard-heading">
    <div class="page-heading">
      <p class="eyebrow">OPERATIONS / ZONE 1</p>
      <h1>Analytics Dashboard</h1>
      <p class="page-description">Your latest operational picture, with every change over the last hour.</p>
    </div>
    <RouterLink to="/settings" class="button primary">Update metrics <span aria-hidden="true">↗</span></RouterLink>
  </div>
  <div class="dashboard-status">
    <span class="refresh-status" :class="{ reconnecting: error }"><span aria-hidden="true" class="status-dot"></span>
      {{ error ? 'Reconnecting' : `Auto-refresh · every ${interval / 1000}s` }}
    </span>
    <span>Latest snapshot: {{ snapshotTime }}</span>
  </div>
  <div v-if="error" class="notice error-notice dashboard-notice" role="alert">
    <div><strong>Unable to refresh analytics.</strong> {{ error }}
      <p v-if="data">Showing the last successful update from {{ new Date(updatedAt).toLocaleTimeString() }}.</p>
    </div>
    <button type="button" class="button secondary" :disabled="refreshing" @click="refresh">Retry now</button>
  </div>
  <div v-if="!data && !error" class="dashboard-loading" role="status">Loading analytics…</div>
  <template v-if="data">
    <p v-if="!data.current.event_id" class="dashboard-zero" role="status">
      No snapshots yet. Publish your first update from Metrics Settings to start tracking activity.
    </p>
    <div class="dashboard-grid">
      <MetricCard v-for="(metric, index) in METRICS" :key="metric.field" :metric="metric"
        :value="data.current[metric.field]" :history="data.history" :window-end="updatedAt" :color="colors[index]" />
    </div>
  </template>
</template>
