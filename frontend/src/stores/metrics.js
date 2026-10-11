import { computed, reactive, ref } from 'vue';
import { defineStore } from 'pinia';
import { getCurrentMetrics, updateMetrics } from '../services/api.js';
import { METRICS, validateMetrics, zeroMetrics } from '../domain/metrics.js';

export const useMetricsStore = defineStore('metrics', () => {
  const values = reactive(zeroMetrics());
  const loading = ref(false);
  const loaded = ref(false);
  const submitting = ref(false);
  const loadError = ref('');
  const submitError = ref('');
  const accepted = ref(null);
  const lastTimestamp = ref(null);
  const errors = computed(() => validateMetrics(values));
  const canSubmit = computed(() => loaded.value && !loading.value && !submitting.value &&
    Object.keys(errors.value).length === 0);

  async function initialize() {
    if (loading.value || submitting.value) return;
    loading.value = true;
    loaded.value = false;
    loadError.value = '';
    accepted.value = null;
    submitError.value = '';
    try {
      const snapshot = await getCurrentMetrics();
      if (snapshot?.zone_id !== 'ZONE_1' || Object.keys(validateMetrics(snapshot)).length) {
        throw new Error('The service returned invalid metric values. Please try again.');
      }
      for (const { field } of METRICS) values[field] = snapshot[field];
      lastTimestamp.value = snapshot.event_timestamp;
      loaded.value = true;
    } catch (error) {
      loadError.value = error.message;
    } finally {
      loading.value = false;
    }
  }

  function setValue(field, value) {
    if (!loaded.value || loading.value || submitting.value) return;
    values[field] = value;
    accepted.value = null;
    submitError.value = '';
  }

  async function submit() {
    if (!canSubmit.value) return;
    submitting.value = true;
    submitError.value = '';
    accepted.value = null;
    const payload = { zone_id: 'ZONE_1', ...values };
    try {
      const result = await updateMetrics(payload);
      if (result.status !== 'accepted' || typeof result.event_id !== 'string' ||
          !Number.isInteger(result.event_timestamp)) {
        throw new Error('Unable to confirm the update. Check current metrics before retrying.');
      }
      accepted.value = result;
    } catch (error) {
      submitError.value = error.message;
    } finally {
      submitting.value = false;
    }
  }

  return { values, loading, loaded, submitting, loadError, submitError, accepted,
    lastTimestamp, errors, canSubmit, initialize, setValue, submit };
});
