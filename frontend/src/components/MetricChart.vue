<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue';
import { Chart, LineController, LineElement, PointElement, LinearScale, Tooltip } from 'chart.js';
import { HOUR_MS } from '../domain/dashboard.js';

Chart.register(LineController, LineElement, PointElement, LinearScale, Tooltip);
const props = defineProps({ label: String, points: Array, windowEnd: Number, color: String });
const canvas = ref(null);
let chart;
const timeLabel = (value) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function updateChart() {
  if (!chart) return;
  chart.data.datasets[0].data = props.points;
  chart.options.scales.x.min = props.windowEnd - HOUR_MS;
  chart.options.scales.x.max = props.windowEnd;
  chart.update('none');
}

onMounted(() => {
  chart = new Chart(canvas.value, {
    type: 'line',
    data: { datasets: [{ label: props.label, data: props.points,
      borderColor: props.color, backgroundColor: props.color,
      borderWidth: 2, pointRadius: 3, pointHoverRadius: 5, tension: 0, fill: false }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, parsing: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: { tooltip: { callbacks: { title: (items) => timeLabel(items[0].parsed.x) } } },
      scales: {
        x: { type: 'linear', min: props.windowEnd - HOUR_MS, max: props.windowEnd,
          grid: { display: false }, border: { display: false },
          ticks: { maxTicksLimit: 5, color: '#7a847d', font: { size: 10 }, callback: timeLabel } },
        y: { type: 'linear', beginAtZero: true, grace: '10%', border: { display: false },
          grid: { color: '#edf0eb' }, ticks: { precision: 0, maxTicksLimit: 4, color: '#7a847d', font: { size: 10 } } },
      },
    },
  });
});
watch(() => [props.points, props.windowEnd], updateChart);
onUnmounted(() => chart?.destroy());
</script>

<template>
  <figure class="metric-chart">
    <div class="chart-canvas">
      <canvas ref="canvas" role="img"
        :aria-label="`${label}: ${points.length} observations in the last hour${points.length ? `; latest observation ${points.at(-1).y}` : ''}`">
        {{ label }} history for the last hour.
      </canvas>
      <p v-if="!points.length" class="chart-empty">No observations in the last hour</p>
    </div>
    <figcaption>Last hour<span>{{ points.length }} {{ points.length === 1 ? 'observation' : 'observations' }}</span></figcaption>
  </figure>
</template>
