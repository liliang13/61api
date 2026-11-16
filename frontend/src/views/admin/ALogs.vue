<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">全局用量</h1>
    <div class="mt-5 flex flex-wrap gap-3">
      <el-input v-model="model" placeholder="按模型筛选" clearable class="!w-64" @keydown.enter="load" />
      <el-button type="primary" @click="load">查询</el-button>
      <span class="ml-auto text-xs text-stone-400">共 {{ total }} 条</span>
    </div>

    <div class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4" v-if="byChannel.length">
      <div v-for="c in byChannel" :key="c.channel" class="rounded-2xl border border-black/5 bg-white p-4">
        <p class="text-xs text-stone-400">{{ c.channel }}</p>
        <p class="mt-1 text-lg font-bold text-stone-800">¥{{ c.quota_yuan.toFixed(4) }}</p>
        <p class="mt-0.5 text-xs text-stone-400">{{ c.requests }} 次调用</p>
      </div>
    </div>
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="165" />
        <el-table-column prop="user_id" label="用户" width="70" align="center">
          <template #default="{ row }">#{{ row.user_id }}</template>
        </el-table-column>
        <el-table-column label="模型" min-width="170">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.model }}</code></template>
        </el-table-column>
        <el-table-column label="实际渠道" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" type="info">{{ row.channel_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="prompt_tokens" label="输入" width="90" align="right" />
        <el-table-column prop="completion_tokens" label="输出" width="90" align="right" />
        <el-table-column label="费用" width="100" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(6) }}</template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时" width="85" align="right">
          <template #default="{ row }">{{ row.latency_ms }}ms</template>
        </el-table-column>
        <el-table-column label="状态" width="85" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.status !== 'ok'" :content="row.error_msg" placement="top">
              <el-tag size="small" type="danger" effect="plain">失败</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" type="success" effect="plain">成功</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { adminLogs } from '../../api'

const items = ref([])
const byChannel = ref([])
const total = ref(0)
const page = ref(1)
const size = 20
const model = ref('')

async function load() {
  const res = await adminLogs({ page: page.value, page_size: size, model: model.value || undefined })
  items.value = res.data.items
  total.value = res.data.total
  byChannel.value = res.data.by_channel || []
}

onMounted(load)
</script>
