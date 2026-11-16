<template>
  <div ref="el" :style="{ height }" class="w-full"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { graphic, init, use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  points: { type: Array, default: () => [] },   // [{ date, requests, quota }]
  height: { type: String, default: '200px' },
})

const el = ref(null)
let chart = null
let observer = null

function buildOption() {
  const dates = props.points.map((p) => p.date)
  const values = props.points.map((p) => p.requests)
  return {
    grid: { left: 6, right: 6, top: 26, bottom: 2, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(79,70,229,0.06)' } },
      backgroundColor: '#1c1917',
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { color: '#fafaf9', fontSize: 12 },
      formatter: (params) => {
        const p = params[0]
        const item = props.points[p.dataIndex]
        const quota = item && item.quota ? `<br/>消费 ¥${(item.quota / 500000).toFixed(4)}` : ''
        return `${p.name}<br/>调用 <b>${p.value}</b> 次${quota}`
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#a8a29e', fontSize: 11, margin: 12 },
    },
    yAxis: { type: 'value', show: false },
    series: [{
      type: 'bar',
      data: values,
      barWidth: '52%',
      barMaxWidth: 26,
      itemStyle: {
        borderRadius: [6, 6, 2, 2],
        color: new graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#818cf8' },
          { offset: 1, color: '#4f46e5' },
        ]),
      },
      label: {
        show: true,
        position: 'top',
        color: '#78716c',
        fontSize: 10,
        fontWeight: 600,
        formatter: (p) => (p.value > 0 ? p.value : ''),
      },
    }],
  }
}

function render() {
  if (chart) chart.setOption(buildOption(), true)
}

onMounted(() => {
  chart = init(el.value)
  render()
  observer = new ResizeObserver(() => chart && chart.resize())
  observer.observe(el.value)
})

watch(() => props.points, render, { deep: true })

onBeforeUnmount(() => {
  observer && observer.disconnect()
  chart && chart.dispose()
  chart = null
})
</script>
