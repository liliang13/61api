<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h1 class="text-xl font-bold text-stone-800">工单支持</h1>
      <div class="flex items-center gap-2">
        <button v-for="s in statusTabs" :key="s.value" @click="selectStatus(s.value)"
          class="rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors"
          :class="status === s.value
            ? 'border-[#4f46e5] bg-[#4f46e5] text-white'
            : 'border-black/10 bg-white text-stone-600 hover:border-[#4f46e5]/40 hover:text-[#4f46e5]'">
          {{ s.label }}<span class="ml-1 text-xs opacity-70">{{ countOf(s.value) }}</span>
        </button>
      </div>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%" class="cursor-pointer"
        @row-click="(row) => $router.push(`/admin/tickets/${row.id}`)">
        <el-table-column label="工单" min-width="260">
          <template #default="{ row }">
            <div class="flex items-center gap-2">
              <span v-if="row.status === 'open'" class="h-2 w-2 shrink-0 rounded-full bg-[#ef4444]"></span>
              <span class="min-w-0 flex-1 truncate font-semibold text-stone-800">{{ row.title }}</span>
            </div>
            <p class="truncate text-xs text-stone-400">{{ row.preview }}</p>
          </template>
        </el-table-column>
        <el-table-column label="用户" width="140">
          <template #default="{ row }">
            <span class="text-sm text-stone-700">{{ row.username }}</span>
            <span class="ml-1 font-mono text-xs text-stone-400">#{{ row.user_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="140" />
        <el-table-column prop="updated_at" label="最后活动" width="140" />
      </el-table>
      <el-empty v-if="!items.length" description="暂无工单" />
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" hide-on-single-page />
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { adminTickets } from '../../api'

const statusTabs = [
  { value: '', label: '全部' },
  { value: 'open', label: '待处理' },
  { value: 'answered', label: '已回复' },
  { value: 'closed', label: '已关闭' },
]
const status = ref('')
const items = ref([])
const counts = ref({})
const total = ref(0)
const page = ref(1)
const size = 15

function statusText(s) {
  return { open: '待处理', answered: '已回复', closed: '已关闭' }[s] || s
}
function statusType(s) {
  return { open: 'warning', answered: 'success', closed: 'info' }[s] || 'info'
}
function countOf(v) {
  return counts.value[v] || 0
}

function selectStatus(v) {
  status.value = v
  page.value = 1
  load()
}

async function load() {
  const res = await adminTickets({ page: page.value, page_size: size, status: status.value || undefined })
  items.value = res.data?.items || []
  total.value = res.data?.total || 0
  if (status.value) counts.value[status.value] = total.value
  else {
    const all = await adminTickets({ page: 1, page_size: 1 })
    const t = all.data?.total || 0
    const o = (await adminTickets({ page: 1, page_size: 1, status: 'open' })).data?.total || 0
    counts.value = { '': t, open: o }
  }
}

onMounted(load)
</script>
