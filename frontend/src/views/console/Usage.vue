<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">用量与计费明细</h1>

    <!-- 筛选 -->
    <div class="mt-4 flex flex-wrap items-center gap-3">
      <el-date-picker v-model="range" type="daterange" range-separator="至" start-placeholder="开始日期"
        end-placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 260px" @change="onFilterChange" />
      <el-select v-model="filter.model" placeholder="全部模型" clearable filterable class="!w-52" @change="onFilterChange">
        <el-option v-for="m in models" :key="m" :label="m" :value="m" />
      </el-select>
      <el-select v-model="filter.key_id" placeholder="全部密钥" clearable class="!w-40" @change="onFilterChange">
        <el-option v-for="k in keys" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-select v-model="filter.status" placeholder="全部状态" clearable class="!w-28" @change="onFilterChange">
        <el-option label="成功" value="ok" />
        <el-option label="失败" value="error" />
      </el-select>
      <el-button @click="resetFilter">重置</el-button>
    </div>

    <!-- 汇总统计 -->
    <div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" v-if="summary">
      <div class="rounded-2xl border border-black/5 bg-white p-4">
        <p class="text-xs text-stone-400">请求数</p>
        <p class="mt-1 text-xl font-bold text-stone-800">{{ summary.requests }}</p>
        <p class="mt-0.5 text-xs text-stone-400">输入 {{ fmtTokens(summary.prompt_tokens) }} / 输出 {{ fmtTokens(summary.completion_tokens) }} tokens</p>
      </div>
      <div class="rounded-2xl border border-black/5 bg-white p-4">
        <p class="text-xs text-stone-400">输入费用</p>
        <p class="mt-1 text-xl font-bold text-stone-800">¥{{ summary.input_cost.toFixed(4) }}</p>
      </div>
      <div class="rounded-2xl border border-black/5 bg-white p-4">
        <p class="text-xs text-stone-400">输出费用</p>
        <p class="mt-1 text-xl font-bold text-stone-800">¥{{ summary.output_cost.toFixed(4) }}</p>
      </div>
      <div class="rounded-2xl border border-black/5 bg-white p-4">
        <p class="text-xs text-stone-400">总费用(实扣)</p>
        <p class="mt-1 text-xl font-bold text-[#4f46e5]">¥{{ summary.quota_yuan.toFixed(4) }}</p>
        <p class="mt-0.5 text-xs text-stone-400">= 输入 + 输出,单次最低 1 quota</p>
      </div>
    </div>

    <!-- 按模型分组 -->
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white" v-if="byModel.length">
      <p class="border-b border-black/5 px-5 py-3 text-sm font-bold text-stone-700">按模型汇总(当前筛选范围)</p>
      <table class="w-full text-sm">
        <thead class="bg-[#fafafa] text-left text-xs text-stone-500">
          <tr>
            <th class="px-5 py-2 font-semibold">模型</th>
            <th class="px-5 py-2 text-right font-semibold">请求</th>
            <th class="px-5 py-2 text-right font-semibold">输入 tokens</th>
            <th class="px-5 py-2 text-right font-semibold">输出 tokens</th>
            <th class="px-5 py-2 text-right font-semibold">费用</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-black/5">
          <tr v-for="m in byModel" :key="m.model">
            <td class="px-5 py-2"><code class="font-mono text-xs">{{ m.model }}</code></td>
            <td class="px-5 py-2 text-right">{{ m.requests }}</td>
            <td class="px-5 py-2 text-right">{{ fmtTokens(m.prompt_tokens) }}</td>
            <td class="px-5 py-2 text-right">{{ fmtTokens(m.completion_tokens) }}</td>
            <td class="px-5 py-2 text-right font-semibold text-stone-700">¥{{ m.quota_yuan.toFixed(4) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 明细表 -->
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="px-6 py-3 text-xs leading-7 text-stone-600">
              <p class="font-semibold text-stone-700">计费复算(单价为调用时点快照,调价不影响历史)</p>
              <p v-if="row.status === 'ok'">
                输入:{{ row.prompt_tokens }} tokens(缓存命中 {{ row.cache_hit_tokens }})按 ¥{{ row.input_rate }}/1M{{ row.cache_rate > 0 ? '(命中部分 ¥' + row.cache_rate + '/1M)' : '' }} =
                <b>¥{{ row.input_cost.toFixed(8) }}</b>
                　输出:{{ row.completion_tokens }} tokens × ¥{{ row.output_rate }}/1M =
                <b>¥{{ row.output_cost.toFixed(8) }}</b>
              </p>
              <p v-if="row.status === 'ok'">
                合计 = ¥{{ (row.input_cost + row.output_cost).toFixed(8) }} → 按 500000/¥ 换算为
                {{ row.quota }} quota(单次最低 1 quota)→ 实扣 <b>¥{{ (row.quota / 500000).toFixed(6) }}</b>
              </p>
              <p v-else>该请求未产生费用(状态:{{ row.status }}{{ row.error_msg ? ' · ' + row.error_msg : '' }})</p>
              <p class="text-stone-400">API 密钥:{{ row.key_display }} · 渠道 #{{ row.channel_id }} · {{ row.stream ? '流式' : '非流式' }}</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="密钥" width="110">
          <template #default="{ row }">{{ row.key_display }}</template>
        </el-table-column>
        <el-table-column label="模型" min-width="160">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.model }}</code></template>
        </el-table-column>
        <el-table-column prop="prompt_tokens" label="输入 tk" width="80" align="right" />
        <el-table-column prop="completion_tokens" label="输出 tk" width="80" align="right" />
        <el-table-column label="费用" width="110" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(6) }}</template>
        </el-table-column>
        <el-table-column label="方式" width="70" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.stream ? 'success' : 'info'" effect="plain">{{ row.stream ? '流式' : '普通' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时" width="80" align="right">
          <template #default="{ row }">{{ row.latency_ms }}ms</template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.status !== 'ok'" :content="row.error_msg" placement="top">
              <el-tag size="small" type="danger" effect="plain">失败</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" type="success" effect="plain">成功</el-tag>
            <el-tooltip v-if="row.billing_source === 'estimated'" content="上游未返回用量,本笔按字符估算计费" placement="top">
              <el-tag size="small" type="warning" effect="plain" class="ml-1">估</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="filter.page_size"
        v-model:current-page="filter.page" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { getUsage, getModelPrices, getKeys } from '../../api'

const items = ref([])
const total = ref(0)
const summary = ref(null)
const byModel = ref([])
const models = ref([])
const keys = ref([])
const range = ref(null)

const filter = reactive({ model: '', key_id: null, status: '', page: 1, page_size: 20 })

const fmtTokens = (n) => (n >= 10000 ? (n / 1000).toFixed(1) + 'k' : String(n))

async function load() {
  const params = {
    page: filter.page, page_size: filter.page_size,
    model: filter.model || undefined, key_id: filter.key_id || undefined,
    status: filter.status || undefined,
  }
  if (range.value && range.value[0]) { params.start = range.value[0]; params.end = range.value[1] }
  else params.days = 30
  const res = await getUsage(params)
  items.value = res.data.items
  total.value = res.data.total
  summary.value = res.data.summary
  byModel.value = res.data.by_model || []
}

function onFilterChange() { filter.page = 1; load() }
function resetFilter() {
  filter.model = ''; filter.key_id = null; filter.status = ''; filter.page = 1
  range.value = null
  load()
}

onMounted(async () => {
  await load()
  const pm = await getModelPrices()
  models.value = (pm.data || []).map((m) => m.name)
  const pk = await getKeys()
  keys.value = pk.data || []
})
</script>
