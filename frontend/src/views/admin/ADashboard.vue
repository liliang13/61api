<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">运营概览</h1>
    <div class="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div v-for="c in cards" :key="c.label" class="rounded-2xl border border-black/5 bg-white p-5">
        <p class="text-xs text-stone-400">{{ c.label }}</p>
        <p class="mt-2 text-2xl font-bold" :class="c.accent || 'text-stone-800'">{{ c.value }}</p>
        <p class="mt-1 text-xs text-stone-400">{{ c.sub }}</p>
      </div>
    </div>

    <div class="mt-6 grid gap-5 lg:grid-cols-2">
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <h2 class="font-bold text-stone-800">近 14 日调用量</h2>
        <div class="mt-4" v-if="stats">
          <BarChart :points="stats.series" />
        </div>
      </div>
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <h2 class="font-bold text-stone-800">最近调用</h2>
        <el-table :data="stats?.recent_logs || []" size="small" class="mt-3">
          <el-table-column prop="created_at" label="时间" width="150" />
          <el-table-column label="模型" min-width="140">
            <template #default="{ row }"><code class="font-mono text-xs">{{ row.model }}</code></template>
          </el-table-column>
          <el-table-column label="渠道" width="100">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" type="info">{{ row.channel_name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="prompt_tokens" label="入" width="70" align="right" />
          <el-table-column prop="completion_tokens" label="出" width="70" align="right" />
          <el-table-column label="费用" width="90" align="right">
            <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(6) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { adminStats } from '../../api'
import BarChart from '../../components/BarChart.vue'
import { useUserStore } from '../../stores/user'

const store = useUserStore()
const stats = ref(null)

const cards = computed(() => {
  if (!stats.value) return []
  const s = stats.value
  return [
    { label: store.isPrivate ? '用户数' : '注册用户', value: String(s.users), sub: store.isPrivate ? `${s.tenants} 个组织 · ${s.keys} 个 API 密钥` : `${s.keys} 个 API 密钥` },
    { label: '今日请求', value: String(s.today.requests), sub: `${s.today.tokens} tokens` },
    { label: '用户持有余额', value: `¥${s.quota_held_yuan.toFixed(6)}`, sub: '总预收余额' },
    { label: '已开票锁定', value: `¥${(s.invoiced_locked_yuan || 0).toFixed(6)}`, sub: '开票部分退款需红冲' },
    { label: '净退款敞口', value: `¥${(s.exposed_yuan || 0).toFixed(6)}`, sub: '未开票余额 · 可正常退款', accent: 'text-[#4f46e5]' },
    ...(store.isPrivate
      ? [{ label: '组织数', value: String(s.tenants), sub: '独立额度与用量边界' }]
      : [{ label: '累计充值', value: `¥${s.revenue_yuan.toFixed(2)}`, sub: '已支付订单总额', accent: 'text-[#4f46e5]' }]),
  ]
})

onMounted(async () => { stats.value = (await adminStats()).data })
</script>
