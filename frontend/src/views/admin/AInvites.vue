<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">邀请审计</h1>
    <p class="mt-2 text-xs text-stone-400">
      邀请奖励在<b>被邀请人累计充值满 ¥{{ minTopup }}</b> 后自动发放;风控拒绝的记录可人工复核发放。
    </p>

    <div class="mt-4 flex gap-2">
      <el-radio-group v-model="statusFilter" @change="load">
        <el-radio-button :value="-1">全部</el-radio-button>
        <el-radio-button :value="0">待发放</el-radio-button>
        <el-radio-button :value="1">已发放</el-radio-button>
        <el-radio-button :value="2">风控拒绝</el-radio-button>
      </el-radio-group>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="150" />
        <el-table-column label="邀请人" min-width="150">
          <template #default="{ row }">
            <div class="text-xs font-semibold text-stone-700">{{ row.from_name }}</div>
            <div class="font-mono text-xs text-stone-400">{{ row.from_uid_code }} #{{ row.from_uid }}</div>
          </template>
        </el-table-column>
        <el-table-column label="被邀请人" min-width="150">
          <template #default="{ row }">
            <div class="text-xs font-semibold text-stone-700">{{ row.to_name }}</div>
            <div class="font-mono text-xs text-stone-400">{{ row.to_uid_code }} #{{ row.to_uid }}</div>
          </template>
        </el-table-column>
        <el-table-column label="奖励" width="90" align="right">
          <template #default="{ row }">¥{{ row.quota_yuan.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="95" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="{ 0: 'warning', 1: 'success', 2: 'danger' }[row.status]">
              {{ { 0: '待发放', 1: '已发放', 2: '已拒绝' }[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 1" link type="primary" size="small" @click="grant(row)">人工发放</el-button>
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminInvites, adminGrantInvite, adminGetSettings } from '../../api'
import { dialogResult } from '../../utils/dialog'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 20
const statusFilter = ref(-1)
const minTopup = ref(10)

async function load() {
  const params = { page: page.value, page_size: size }
  if (statusFilter.value !== -1) params.status = statusFilter.value
  const res = await adminInvites(params)
  items.value = res.data.items
  total.value = res.data.total
}

async function grant(row) {
  if (!await dialogResult(ElMessageBox.confirm(
    `确认人工发放该笔 ¥${row.quota_yuan.toFixed(2)} 邀请奖励给「${row.from_name}」?`,
    '人工发放确认', { type: 'warning' }))) return
  await adminGrantInvite(row.id)
  ElMessage.success('已发放')
  await load()
}

onMounted(async () => {
  await load()
  try {
    const s = await adminGetSettings()
    minTopup.value = s.data.invite_min_topup_yuan ?? 10
  } catch { /* 默认值 */ }
})
</script>
