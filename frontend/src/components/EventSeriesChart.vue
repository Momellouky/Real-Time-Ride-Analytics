<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import { Chart, LineController, LineElement, PointElement, LinearScale, Tooltip, Legend } from 'chart.js';
Chart.register(LineController, LineElement, PointElement, LinearScale, Tooltip, Legend);
const props = defineProps({ label: String, series: Array, windowEnd: Number, duration: Number, bucketWidth: Number });
const canvas = ref(null);
let chart;
const timeLabel = (value) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
function update() {
  if (!chart) return;
  chart.data.datasets = props.series.map((s) => ({ label: s.label, data: s.points, borderColor: s.color,
    backgroundColor: s.color, borderWidth: 2, pointRadius: 2, tension: 0 }));
  chart.options.scales.x.min = Math.floor((props.windowEnd - props.duration) / props.bucketWidth) * props.bucketWidth;
  chart.options.scales.x.max = props.windowEnd;
  chart.update('none');
}
onMounted(() => {
  chart = new Chart(canvas.value, { type: 'line', data: { datasets: [] }, options: {
    responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
    plugins: { legend: { position: 'bottom' }, tooltip: { callbacks: { title: (items) => timeLabel(items[0].parsed.x) } } },
    scales: { x: { type: 'linear', ticks: { maxTicksLimit: 5, callback: timeLabel } },
      y: { beginAtZero: true, ticks: { precision: 0 } } },
  } });
  update();
});
watch(() => [props.series, props.windowEnd], update);
onUnmounted(() => chart?.destroy());
</script>
<template>
  <div class="event-chart-canvas">
    <canvas ref="canvas" role="img" :aria-label="`${label}: ${series.map(s => `${s.label} ${s.points.length} buckets`).join(', ')}`" />
    <p v-if="series.every(s => !s.points.length)" class="chart-empty">No ingested events in this window</p>
  </div>
</template>
