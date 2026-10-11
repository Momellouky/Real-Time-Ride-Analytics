import { computed, reactive, ref } from 'vue';
import { defineStore } from 'pinia';
import { getGeneratorStatus, startGenerator, stopGenerator } from '../services/api.js';
import { ACTIVE_STATES, RATE_PRESETS, generatorErrors, generatorInput, validateGeneratorStatus } from '../domain/generator.js';

export const useGeneratorStore = defineStore('generator', () => {
  const draft = reactive({ user_count: 10000, driver_count: 2000, rate: 250, custom_rate: 1250 });
  const current = ref(null);
  const loaded = ref(false);
  const refreshing = ref(false);
  const pending = ref('');
  const statusError = ref('');
  const commandError = ref('');
  const feedback = ref('');
  let timer = null;
  let watching = false;
  let revision = 0;
  let controller = null;
  const errors = computed(() => generatorErrors(draft));
  const active = computed(() => ACTIVE_STATES.includes(current.value?.status));
  const canEdit = computed(() => loaded.value && !active.value && !pending.value && !statusError.value);
  const canStart = computed(() => canEdit.value && Object.keys(errors.value).length === 0);
  const canStop = computed(() => loaded.value && !pending.value &&
    ['WARMING_UP', 'RUNNING'].includes(current.value?.status));
  const highRate = computed(() => generatorInput(draft).target_events_per_second > 1000);

  function accept(data) {
    const next = validateGeneratorStatus(data);
    if (next.simulation_id && (!loaded.value || next.simulation_id !== current.value?.simulation_id)) {
      draft.user_count = next.user_pool_size;
      draft.driver_count = next.driver_pool_size;
      draft.rate = RATE_PRESETS.includes(next.target_events_per_second) ? next.target_events_per_second : 'custom';
      if (draft.rate === 'custom') draft.custom_rate = next.target_events_per_second;
    }
    current.value = next;
    loaded.value = true;
    statusError.value = '';
  }

  async function refresh() {
    if (refreshing.value || pending.value) return;
    const session = revision;
    const requestController = new AbortController();
    controller = requestController;
    refreshing.value = true;
    try {
      const data = await getGeneratorStatus(requestController.signal);
      if (session === revision) accept(data);
    } catch (error) {
      if (session === revision) statusError.value = error.message;
    } finally {
      if (controller === requestController) controller = null;
      if (session === revision) refreshing.value = false;
    }
  }

  function watch() {
    if (watching) return;
    watching = true;
    loaded.value = false;
    statusError.value = '';
    revision++;
    timer = setInterval(() => void refresh(), 1000);
    void refresh();
  }

  function unwatch() {
    watching = false;
    revision++;
    clearInterval(timer);
    timer = null;
    controller?.abort();
    controller = null;
    refreshing.value = false;
  }

  async function command(kind) {
    if (kind === 'start' ? !canStart.value : !canStop.value) return;
    // Discard any pre-command poll so an old STOPPED response cannot overwrite Start.
    revision++;
    controller?.abort();
    controller = null;
    refreshing.value = false;
    pending.value = kind;
    commandError.value = '';
    feedback.value = '';
    try {
      const result = kind === 'start' ? await startGenerator(generatorInput(draft)) : await stopGenerator();
      accept(result);
      feedback.value = result.status === 'ERROR' ? '' : kind === 'start'
        ? 'Fresh simulation started.' : 'Generator stopped. Final statistics are retained.';
    } catch (error) {
      commandError.value = `${error.message} Refreshing generator status before another command.`;
      // A timed-out control request may still have succeeded on the server.
      statusError.value = 'Confirming the generator state…';
    } finally {
      pending.value = '';
      await refresh();
    }
  }

  return { draft, current, loaded, refreshing, pending, statusError, commandError, feedback,
    errors, active, canEdit, canStart, canStop, highRate, refresh, watch, unwatch,
    start: () => command('start'), stop: () => command('stop') };
});
