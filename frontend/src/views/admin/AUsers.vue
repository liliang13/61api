<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">用户管理</h1>
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </div>
    <div class="mt-5 flex flex-wrap gap-3">
      <el-input v-model="search" placeholder="搜索 UID / 用户名 / 手机号" clearable class="!w-72" @keydown.enter="load" />
      <el-select v-model="tenantFilter" placeholder="全部组织" clearable class="!w-48" @change="load">
        <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="UID" width="90">
          <template #default="{ row }"><code class="font-mono text-xs font-bold">{{ row.uid || '-' }}</code></template>
        </el-table-column>
        <el-table-column label="用户名" min-width="120">
          <template #default="{ row }">
            {{ row.username }}
            <el-tag v-if="row.deleted_at" size="small" type="danger" effect="plain" class="ml-1">已注销</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属组织" min-width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.tenant_name || '未分配' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="手机号" width="120">
          <template #default="{ row }">{{ row.deleted_at ? (row.deleted_phone || '-') : row.phone }}</template>
        </el-table-column>
        <el-table-column label="余额" width="110" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(6) }}</template>
        </el-table-column>
        <el-table-column label="累计消费" width="110" align="right">
          <template #default="{ row }">¥{{ (row.used_quota / 500000).toFixed(6) }}</template>
        </el-table-column>
        <el-table-column label="并发" width="80" align="center">
          <template #default="{ row }">
            <span v-if="row.concurrency_limit > 0" class="font-semibold text-[#4f46e5]">{{ row.concurrency_limit }}</span>
            <span v-else class="text-xs text-stone-400">默认</span>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'warning' : 'info'" effect="plain">{{ row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-if="!row.deleted_at" :model-value="row.status === 1" @change="toggleStatus(row)" />
            <el-tooltip v-else content="已注销账户不可操作" placement="top">
              <el-tag size="small" type="info" effect="plain">注销</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="最后登录" min-width="150">
          <template #default="{ row }">
            <div class="text-xs text-stone-600">{{ row.last_login_at || '从未' }}</div>
            <div class="font-mono text-xs text-stone-400">{{ row.last_login_ip || '' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openAdjust(row)">调额</el-button>
            <el-button link type="primary" size="small" @click="openUsage(row)">用量</el-button>
            <el-button link type="warning" size="small" @click="openReset(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>

    <!-- 新建用户 -->
    <el-dialog v-model="create.visible" title="新建用户" width="480">
      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="create.username" placeholder="3-64 位字母、数字、下划线" />
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="create.password" type="password" show-password placeholder="至少 10 位且含字母和数字" />
        </el-form-item>
        <el-form-item label="所属组织">
          <el-select v-model="create.tenant_id" class="!w-full" placeholder="选择组织">
            <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="create.role">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="初始额度(CNY)">
          <el-input-number v-model="create.quota_yuan" :min="0" :precision="2" class="!w-full" />
        </el-form-item>
        <el-form-item label="手机号(选填)">
          <el-input v-model="create.phone" maxlength="11" placeholder="仅作联系信息,不用于登录" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="create.visible = false">取消</el-button>
        <el-button type="primary" :loading="create.saving" @click="saveCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="reset.visible" :title="`重置密码 · ${reset.user?.username || ''}`" width="420">
      <el-form label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="reset.password" type="password" show-password placeholder="至少 10 位且含字母和数字" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reset.visible = false">取消</el-button>
        <el-button type="primary" :loading="reset.saving" @click="saveReset">确认重置</el-button>
      </template>
    </el-dialog>

    <!-- 用户用量明细 -->
    <el-dialog v-model="usage.visible" :title="`用量明细 · ${usage.user?.username || ''} (${usage.user?.uid || ''})`" width="900">
      <div v-if="usage.summary" class="mb-3 grid grid-cols-4 gap-3">
        <div class="rounded-xl bg-[#fafafa] p-3">
          <p class="text-xs text-stone-400">调用次数</p>
          <p class="mt-1 font-bold text-stone-800">{{ usage.summary.requests }}</p>
        </div>
        <div class="rounded-xl bg-[#fafafa] p-3">
          <p class="text-xs text-stone-400">输入 tokens</p>
          <p class="mt-1 font-bold text-stone-800">{{ usage.summary.prompt_tokens }}</p>
        </div>
        <div class="rounded-xl bg-[#fafafa] p-3">
          <p class="text-xs text-stone-400">输出 tokens</p>
          <p class="mt-1 font-bold text-stone-800">{{ usage.summary.completion_tokens }}</p>
        </div>
        <div class="rounded-xl bg-[#eef2ff] p-3">
          <p class="text-xs text-stone-400">总消费</p>
          <p class="mt-1 font-bold text-[#4f46e5]">¥{{ usage.summary.quota_yuan.toFixed(4) }}</p>
        </div>
      </div>
      <div v-if="usage.byChannel.length" class="mb-3 flex flex-wrap gap-2">
        <el-tag v-for="c in usage.byChannel" :key="c.channel" size="small" effect="plain">
          {{ c.channel }}:{{ c.requests }} 次 ¥{{ c.quota_yuan.toFixed(4) }}
        </el-tag>
      </div>
      <el-table :data="usage.items" size="small" max-height="360">
        <el-table-column prop="created_at" label="时间" width="150" />
        <el-table-column label="模型" min-width="150">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.model }}</code></template>
        </el-table-column>
        <el-table-column label="渠道" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" type="info">{{ row.channel_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="prompt_tokens" label="输入 tk" width="80" align="right" />
        <el-table-column prop="completion_tokens" label="输出 tk" width="80" align="right" />
        <el-table-column label="费用" width="100" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(6) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="70" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'ok' ? 'success' : 'danger'" effect="plain">
              {{ row.status === 'ok' ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      <div class="mt-3 flex justify-center">
        <el-pagination layout="prev, pager, next, total" :total="usage.total" :page-size="20"
          v-model:current-page="usage.page" @current-change="loadUsage" hide-on-single-page />
      </div>
    </el-dialog>

    <!-- 调整额度 -->
    <el-dialog v-model="dlg.visible" :title="`账户调整 · ${dlg.user?.username || dlg.user?.id}`" width="420">
      <el-form label-position="top">
        <el-form-item label="增加额度(CNY,负数为扣减)">
          <el-input-number v-model="dlg.addCny" :precision="2" :step="1" class="!w-full" />
        </el-form-item>
        <el-form-item label="或直接设定余额(CNY,留空不改)">
          <el-input v-model="dlg.setCny" placeholder="如 10.00" />
        </el-form-item>
        <el-form-item label="并发上限(0 = 使用全局默认)">
          <el-input-number v-model="dlg.concurrencyLimit" :min="0" :max="256" :step="4" class="!w-full" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="saveAdjust">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  adminCreateUser, adminLogs, adminResetUserPassword, adminTenants, adminUpdateUser, adminUsers,
} from '../../api'

const items = ref([])
const tenants = ref([])
const total = ref(0)
const page = ref(1)
const size = 20
const search = ref('')
const tenantFilter = ref('')
const dlg = reactive({ visible: false, user: null, addCny: 0, setCny: '', concurrencyLimit: 0, saving: false })
const usage = reactive({ visible: false, user: null, items: [], summary: null, byChannel: [], total: 0, page: 1 })
const create = reactive({ visible: false, username: '', password: '', tenant_id: '', role: 'user', quota_yuan: 0, phone: '', saving: false })
const reset = reactive({ visible: false, user: null, password: '', saving: false })

async function loadTenants() {
  tenants.value = (await adminTenants()).data
}

async function openUsage(row) {
  usage.user = row
  usage.page = 1
  usage.visible = true
  await loadUsage()
}

async function loadUsage() {
  const res = await adminLogs({ user_id: usage.user.id, page: usage.page, page_size: 20 })
  usage.items = res.data.items
  usage.summary = res.data.summary
  usage.byChannel = res.data.by_channel || []
  usage.total = res.data.total
}

async function load() {
  const params = { page: page.value, page_size: size, search: search.value }
  if (tenantFilter.value) params.tenant_id = tenantFilter.value
  const res = await adminUsers(params)
  items.value = res.data.items
  total.value = res.data.total
}

async function toggleStatus(row) {
  await adminUpdateUser(row.id, { status: row.status === 1 ? 0 : 1 })
  ElMessage.success('已更新')
  await load()
}

function openAdjust(row) {
  dlg.user = row
  dlg.addCny = 0
  dlg.setCny = ''
  dlg.concurrencyLimit = row.concurrency_limit || 0
  dlg.visible = true
}

async function saveAdjust() {
  dlg.saving = true
  try {
    await adminUpdateUser(dlg.user.id, {
      quota_add_yuan: dlg.addCny || undefined,
      quota_set_yuan: dlg.setCny === '' ? undefined : Number(dlg.setCny),
      concurrency_limit: dlg.concurrencyLimit ?? 0,
    })
    ElMessage.success('已保存')
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

function openCreate() {
  Object.assign(create, {
    visible: true, username: '', password: '', role: 'user',
    tenant_id: tenantFilter.value || tenants.value[0]?.id || '',
    quota_yuan: 0, phone: '', saving: false,
  })
}

async function saveCreate() {
  create.saving = true
  try {
    await adminCreateUser({
      username: create.username,
      password: create.password,
      tenant_id: create.tenant_id,
      role: create.role,
      quota_yuan: create.quota_yuan,
      phone: create.phone || undefined,
    })
    ElMessage.success('用户已创建')
    create.visible = false
    await load()
  } finally { create.saving = false }
}

function openReset(row) {
  reset.user = row
  reset.password = ''
  reset.visible = true
}

async function saveReset() {
  reset.saving = true
  try {
    await adminResetUserPassword(reset.user.id, reset.password)
    ElMessage.success('密码已重置,该用户需重新登录')
    reset.visible = false
  } finally { reset.saving = false }
}

onMounted(async () => {
  await loadTenants()
  await load()
})
</script>
