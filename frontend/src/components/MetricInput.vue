<script setup>
import { MAX_METRIC_VALUE } from '../domain/metrics.js';
defineProps({ metric: Object, modelValue: [Number, String], error: String });
const emit = defineEmits(['update:modelValue']);
function update(event) {
  const raw = event.target.value;
  emit('update:modelValue', raw === '' ? '' : Number(raw));
}
</script>

<template>
  <div class="metric-input" :class="{ 'has-error': error }">
    <label :for="metric.field">{{ metric.label }}</label>
    <p :id="`${metric.field}-hint`" class="input-hint">{{ metric.description }}</p>
    <input :id="metric.field" :name="metric.field" type="number" min="0" :max="MAX_METRIC_VALUE"
      step="1" required :value="modelValue" @input="update" :aria-invalid="Boolean(error)"
      :aria-describedby="`${metric.field}-hint${error ? ` ${metric.field}-error` : ''}`" />
    <p v-if="error" :id="`${metric.field}-error`" class="field-error">{{ error }}</p>
  </div>
</template>
