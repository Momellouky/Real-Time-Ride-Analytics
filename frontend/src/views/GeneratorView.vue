<script setup>
import { onMounted, onUnmounted } from 'vue';
import { useGeneratorStore } from '../stores/generator.js';
import { RATE_PRESETS } from '../domain/generator.js';

const store = useGeneratorStore();
const format = (value) => value == null ? '—' : value.toLocaleString();
const diagnostics = [ ['idle_users', 'Idle users'], ['waiting_users', 'Users waiting for a driver'],
  ['users_in_ride', 'Users in a ride'], ['offline_drivers', 'Offline drivers'],
  ['waiting_drivers', 'Waiting drivers'], ['assigned_drivers', 'Assigned drivers'] ];
onMounted(store.watch);
onUnmounted(store.unwatch);
</script>

<template>
  <div class="page-heading">
    <p class="eyebrow">EVENT OPERATIONS / ZONE 1</p>
    <h1>Ride Event Generator</h1>
    <p class="page-description">Run a fresh ride simulation. Control the population and event rate, and monitor its progress.</p>
  </div>
  <div class="settings-layout generator-layout">
    <section class="form-panel" aria-labelledby="generator-controls">
      <div class="panel-heading"><div><h2 id="generator-controls">Simulation controls</h2>
        <p>Each Start creates a new run. Previous runs remain available.</p></div><span class="panel-tag">ZONE_1</span></div>
      <div v-if="!store.loaded && !store.statusError" class="notice" role="status">Loading generator status…</div>
      <div v-if="store.statusError" class="notice error-notice" role="alert">
        <p>{{ store.statusError }}</p><button class="button secondary" type="button" @click="store.refresh">Retry status</button>
      </div>
      <form @submit.prevent="store.start" novalidate>
        <fieldset :disabled="!store.canEdit">
          <legend class="sr-only">Simulation configuration</legend>
          <div class="inputs-grid">
            <div v-for="[field, label] in [['user_count', 'User pool'], ['driver_count', 'Driver pool']]" :key="field">
              <label :for="field">{{ label }}</label><p class="input-hint">Number of {{ field === 'user_count' ? 'users' : 'drivers' }} in the new run.</p>
              <input :id="field" v-model="store.draft[field]" type="number" min="1" step="1" inputmode="numeric"
                :aria-invalid="!!store.errors[field]" :aria-describedby="`${field}-error`" />
              <p :id="`${field}-error`" v-if="store.errors[field]" class="field-error">{{ store.errors[field] }}</p>
            </div>
          </div>
          <h3 id="throughput-label">Target event rate</h3>
          <div class="rate-options" role="radiogroup" aria-labelledby="throughput-label">
            <label v-for="rate in RATE_PRESETS" :key="rate" :class="{ selected: store.draft.rate === rate }">
              <input v-model="store.draft.rate" type="radio" name="rate" :value="rate" />{{ rate }} events/s
            </label>
            <label :class="{ selected: store.draft.rate === 'custom' }">
              <input v-model="store.draft.rate" type="radio" name="rate" value="custom" />Custom
            </label>
          </div>
          <div v-if="store.draft.rate === 'custom'" class="custom-rate">
            <label for="custom_rate">Custom events per second</label>
            <input id="custom_rate" v-model="store.draft.custom_rate" type="number" min="1" step="1" inputmode="numeric"
              :aria-invalid="!!store.errors.target_events_per_second" aria-describedby="rate-error" />
          </div>
          <p v-if="store.errors.target_events_per_second" id="rate-error" class="field-error">{{ store.errors.target_events_per_second }}</p>
          <p v-if="store.highRate" class="rate-warning" role="status">Rates above 1,000 events/s can increase resource usage. Monitor ingestion freshness, memory, and CPU.</p>
        </fieldset>
        <div v-if="store.commandError" class="notice error-notice" role="alert">{{ store.commandError }}</div>
        <div v-if="store.feedback" class="notice success-notice" role="status">{{ store.feedback }}</div>
        <div class="form-footer generator-buttons">
          <button class="button primary" type="submit" :disabled="!store.canStart">{{ store.pending === 'start' ? 'Starting…' : 'Start Generator' }}</button>
          <button class="button secondary" type="button" :disabled="!store.canStop" @click="store.stop">{{ store.pending === 'stop' ? 'Stopping…' : 'Stop Generator' }}</button>
        </div>
      </form>
    </section>
    <aside class="context-panel" aria-labelledby="generator-status-title">
      <p class="eyebrow">LIVE GENERATOR</p><h2 id="generator-status-title">Run progress</h2>
      <p class="generator-state" aria-live="polite">Status: <strong data-testid="generator-state">{{ store.loaded ? store.current.status : 'UNKNOWN' }}</strong></p>
      <p class="simulation-id">Simulation: <span data-testid="simulation-id">{{ store.loaded ? store.current.simulation_id || 'No run yet' : 'Waiting for status' }}</span></p>
      <p v-if="store.current?.last_error" class="notice error-notice" role="alert">Run failed: {{ store.current.last_error }}</p>
      <dl class="generator-stats">
        <div><dt>Target rate</dt><dd>{{ format(store.current?.target_events_per_second) }} events/s</dd></div>
        <div><dt>Actual rate</dt><dd>{{ format(store.current?.actual_events_per_second) }} events/s</dd></div>
        <div><dt>Generated events</dt><dd data-testid="generated-events">{{ format(store.current?.generated_events) }}</dd></div>
        <div><dt>Published events</dt><dd>{{ format(store.current?.published_events) }}</dd></div>
        <div><dt>Users</dt><dd>{{ format(store.current?.user_pool_size) }}</dd></div>
        <div><dt>Drivers</dt><dd>{{ format(store.current?.driver_pool_size) }}</dd></div>
      </dl>
      <p>Actual rate measures acknowledged publication. Pinot ingestion is asynchronous.</p>
    </aside>
  </div>
  <section class="generator-diagnostics form-panel" aria-labelledby="diagnostics-title">
    <div class="panel-heading"><div><h2 id="diagnostics-title">Population diagnostics</h2>
      <p>Current generator state. Final counts remain visible after Stop.</p></div></div>
    <dl class="diagnostics-grid"><div v-for="[field, label] in diagnostics" :key="field"><dt>{{ label }}</dt>
      <dd>{{ format(store.current?.in_memory?.[field]) }}</dd></div></dl>
  </section>
</template>
