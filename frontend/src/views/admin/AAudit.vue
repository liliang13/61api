<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">审计日志</h1>
    <p class="mt-1 text-sm text-stone-500">登录、用户/组织、密钥、渠道、模型和站点设置的变更留痕。</p>

    <div class="mt-5 flex flex-wrap gap-3">
      <el-input v-model="search" placeholder="操作人 / 详情 / 对象 ID" clearable class="!w-64" @keydown.enter="load" />
      <el-select v-model="action" placeholder="全部动作" clearable class="!w-48" @change="load">
        <el-option v-for="a in actions" :key="a" :label="actionLabel(a)" :value="a" />
      </el-select>
      <el-select v-model="tenantId" placeholder="全部组织" clearable class="!w-44" @change="load">
        <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="操作人" width="140">
          <template #default="{ row }">
            <span class="text-sm text-stone-700">{{ row.actor_name || '-' }}</span>
            <span class="ml-1 text-xs text-stone-400">#{{ row.actor_id || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="170">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="tagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="对象" width="130">
          <template #default="{ row }">
            <span class="text-xs text-stone-500">{{ row.target_type || '-' }}</span>
            <span class="ml-1 font-mono text-xs">{{ row.target_id || '' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="详情" min-width="260" show-overflow-tooltip />
        <el-table-column label="组织" width="120">
          <template #default="{ row }">{{ tenantName(row.tenant_id) }}</template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130" />
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
import { adminAudit, adminTenants } from '../../api'

const items = ref([])
const tenants = ref([])
const total = ref(0)
const page = ref(1)
const size = 20
const search = ref('')
const action = ref('')
const tenantId = ref('')

const actions = [
  'auth.login', 'auth.login_failed', 'auth.password_change', 'auth.password_reset',
  'user.create', 'user.update', 'user.password_reset',
  'tenant.create', 'tenant.update',
  'key.create', 'key.update', 'key.delete',
  'channel.create', 'channel.update', 'channel.delete',
  'model.create', 'model.update', 'model.delete',
  'settings.update',
]

const labels = {
  'auth.login': '登录',
  'auth.login_failed': '登录失败',
  'auth.password_change': '修改密码',
  'auth.password_reset': '重置密码',
  'user.create': '创建用户',
  'user.update': '修改用户',
  'user.password_reset': '管理员重置密码',
  'tenant.create': '创建组织',
  'tenant.update': '修改组织',
  'key.create': '创建密钥',
  'key.update': '修改密钥',
  'key.delete': '删除密钥',
  'channel.create': '创建渠道',
  'channel.update': '修改渠道',
  'channel.delete': '删除渠道',
  'model.create': '创建模型',
  'model.update': '修改模型',
  'model.delete': '删除模型',
  'settings.update': '修改站点设置',
}

function actionLabel(value) {
  return labels[value] || value
}

function tagType(value) {
  if (value.includes('delete') || value.includes('failed')) return 'danger'
  if (value.includes('create')) return 'success'
  if (value.includes('update') || value.includes('change') || value.includes('reset')) return 'warning'
  return 'info'
}

function tenantName(id) {
  return tenants.value.find((t) => t.id === id)?.name || '-'
}

async function load() {
  const params = { page: page.value, page_size: size }
  if (search.value) params.search = search.value
  if (action.value) params.action = action.value
  if (tenantId.value) params.tenant_id = tenantId.value
  const res = await adminAudit(params)
  items.value = res.data.items
  total.value = res.data.total
}

onMounted(async () => {
  try { tenants.value = (await adminTenants()).data } catch { /* 组织加载失败不影响审计列表 */ }
  await load()
})
</script>
