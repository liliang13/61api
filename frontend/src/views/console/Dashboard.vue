<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">数据看板</h1>
    <div v-if="store.isPrivate && dashboard?.tenant"
      class="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 rounded-2xl border border-[#4f46e5]/10 bg-[#eef2ff] px-5 py-3 text-sm">
      <span class="font-bold text-[#4f46e5]">{{ dashboard.tenant.name }}</span>
      <span class="text-stone-500">组织剩余额度:<b class="text-stone-700">{{ dashboard.tenant.quota < 0 ? '不限' : '¥' + dashboard.tenant.quota_yuan.toFixed(2) }}</b></span>
      <span class="text-stone-500">组织累计消费:<b class="text-stone-700">¥{{ dashboard.tenant.used_yuan.toFixed(2) }}</b></span>
    </div>
    <div class="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div v-for="c in cards" :key="c.label" class="rounded-2xl border border-black/5 bg-white p-5">
        <p class="text-xs text-stone-400">{{ c.label }}</p>
        <p class="mt-2 text-2xl font-bold" :class="c.accent || 'text-stone-800'">{{ c.value }}</p>
        <p class="mt-1 text-xs text-stone-400">{{ c.sub }}</p>
      </div>
    </div>

    <div class="mt-6 grid gap-5 lg:grid-cols-2">
      <!-- 7日用量 -->
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <h2 class="font-bold text-stone-800">近 7 日调用</h2>
        <BarChart v-if="dashboard" class="mt-4" :points="dashboard.week" />
      </div>

      <!-- 热门模型 -->
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <h2 class="font-bold text-stone-800">近 7 日消费 Top 模型</h2>
        <template v-if="dashboard?.top_models?.length">
          <div v-for="m in dashboard.top_models" :key="m.model" class="mt-4">
            <div class="flex justify-between text-xs">
              <span class="font-mono text-stone-600">{{ m.model }}</span>
              <span class="text-stone-400">¥{{ (m.quota / 500000).toFixed(6) }} · {{ m.requests }} 次</span>
            </div>
            <el-progress :percentage="pct(m.quota)" :show-text="false" :stroke-width="8" class="mt-1.5" />
          </div>
        </template>
        <p v-else class="mt-8 text-center text-sm text-stone-400">还没有调用记录,接入后将在这里展示用量趋势</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getDashboard } from '../../api'
import BarChart from '../../components/BarChart.vue'
import { useUserStore } from '../../stores/user'

const store = useUserStore()
const dashboard = ref(null)

const cards = computed(() => {
  if (!dashboard.value) return []
  const d = dashboard.value
  return [
    { label: '当前余额', value: `¥${d.quota_yuan.toFixed(6)}`, sub: store.isPrivate ? `所属组织:${d.tenant?.name || '未分配'}` : '可随时充值', accent: 'text-[#4f46e5]' },
    { label: '累计消费', value: `¥${d.used_yuan.toFixed(6)}`, sub: '历史总支出' },
    { label: '今日请求', value: String(d.today.requests), sub: '次' },
    { label: '今日消费', value: `¥${(d.today.quota / 500000).toFixed(6)}`, sub: `${d.today.tokens} tokens` },
  ]
})

function pct(q) {
  const top = dashboard.value?.top_models?.[0]?.quota || 1
  return Math.round((q / top) * 100)
}

onMounted(async () => { dashboard.value = (await getDashboard()).data })
</script>
