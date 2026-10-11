<script setup>
import { computed } from 'vue';
import MetricChart from './MetricChart.vue';
import { toSeries } from '../domain/dashboard.js';
const props = defineProps({ metric: Object, value: Number, history: Array, windowEnd: Number, color: String });
const points = computed(() => toSeries(props.history, props.metric.field));
</script>

<template>
  <article class="metric-card" :data-metric="metric.field" :aria-labelledby="`${metric.field}-title`">
    <div class="metric-card-heading">
      <h2 :id="`${metric.field}-title`">{{ metric.label }}</h2>
      <span class="metric-dot" :style="{ background: color }" aria-hidden="true"></span>
    </div>
    <p class="metric-value" :aria-label="`${metric.label}: ${value}`">{{ value.toLocaleString() }}</p>
    <p class="metric-description">{{ metric.description }}</p>
    <MetricChart :label="metric.label" :points="points" :window-end="windowEnd" :color="color" />
  </article>
</template>
