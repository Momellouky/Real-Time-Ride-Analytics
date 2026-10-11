<script setup>
import { computed, onMounted } from 'vue';
import { useMetricsStore } from '../stores/metrics.js';
import { METRICS } from '../domain/metrics.js';
import MetricInput from '../components/MetricInput.vue';

const store = useMetricsStore();
const updatedAt = computed(() => store.lastTimestamp
  ? new Date(store.lastTimestamp).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  : 'No snapshots yet');
const pending = computed(() => Object.keys(store.errors).length ? '—'
  : store.values.ride_requests - store.values.accepted_requests - store.values.cancelled_requests);
onMounted(() => store.initialize());
</script>

<template>
  <div class="page-heading">
    <p class="eyebrow">OPERATIONS / ZONE 1</p>
    <h1>Metrics Settings</h1>
    <p class="page-description">Keep your operational picture up to date. Adjust the values below and publish a snapshot.</p>
  </div>
  <div class="settings-layout">
    <section class="form-panel" aria-labelledby="snapshot-title" :aria-busy="store.loading || store.submitting">
      <div class="panel-heading">
        <div><h2 id="snapshot-title">Operational snapshot</h2><p>All five values are included in every update.</p></div>
        <span class="panel-tag">ZONE_1</span>
      </div>
      <div v-if="store.loading" class="notice" role="status">Loading current metrics…</div>
      <div v-if="store.loadError" class="notice error-notice" role="alert">
        <p>{{ store.loadError }}</p>
        <button type="button" class="button secondary" @click="store.initialize">Retry loading</button>
      </div>
      <form @submit.prevent="store.submit" novalidate>
        <fieldset :disabled="!store.loaded || store.loading || store.submitting">
          <legend class="sr-only">Zone 1 metric values</legend>
          <div class="inputs-grid">
            <MetricInput v-for="metric in METRICS" :key="metric.field" :metric="metric"
              :model-value="store.values[metric.field]" :error="store.loaded ? store.errors[metric.field] : ''"
              @update:model-value="store.setValue(metric.field, $event)" />
          </div>
        </fieldset>
        <div v-if="store.submitError" class="notice error-notice" role="alert">{{ store.submitError }}</div>
        <div v-if="store.accepted" class="notice success-notice" role="status">
          <strong>Snapshot published.</strong> Your update was accepted and will appear in current metrics shortly.
        </div>
        <div class="form-footer">
          <p>Publish a complete snapshot for Zone 1.</p>
          <button class="button primary" type="submit" :disabled="!store.canSubmit">
            {{ store.submitting ? 'Publishing…' : 'Publish snapshot' }}<span aria-hidden="true">↗</span>
          </button>
        </div>
      </form>
    </section>
    <aside class="context-panel" aria-labelledby="context-title">
      <p class="eyebrow">SNAPSHOT GUIDE</p>
      <h2 id="context-title">A complete picture,<br />every update.</h2>
      <p>Change one metric or several. The other values stay in place and are published together.</p>
      <div class="context-stat"><span>Pending requests in this draft</span><strong>{{ pending }}</strong></div>
      <ul class="guidelines">
        <li>Use whole numbers, zero or greater.</li>
        <li>Accepted + cancelled cannot exceed total requests.</li>
        <li>Waiting drivers cannot exceed online drivers.</li>
      </ul>
      <div class="snapshot-time"><span>Latest stored snapshot</span><p>{{ store.loaded ? updatedAt : 'Waiting for current metrics' }}</p></div>
    </aside>
  </div>
</template>
