<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">资源包</h1>
      <el-button type="primary" @click="openEdit(null)">新建资源包</el-button>
    </div>

    <!-- 注册赠送设置 -->
    <div class="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-black/5 bg-white p-4">
      <span class="text-sm font-semibold text-stone-700">注册赠送</span>
      <el-switch v-model="gift.enabled" active-text="开启" inactive-text="关闭" inline-prompt />
      <el-select v-model="gift.packId" placeholder="选择赠送的资源包" class="!w-80" :disabled="!gift.enabled">
        <el-option v-for="p in defs" :key="p.id" :value="p.id"
          :label="`${p.name}(${fmtTokens(p.tokens)} · ${p.model})`" />
      </el-select>
      <el-button type="primary" :loading="gift.saving" @click="saveGift">保存设置</el-button>
      <p class="text-xs text-stone-400">新用户注册与管理员建号时自动发放所选 tokens 资源包(建议选「仅赠送」的包)</p>
    </div>

    <!-- 资源包商品 -->
    <h2 class="mt-6 font-bold text-stone-800">资源包定义</h2>
    <div class="mt-3 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="defs" style="width: 100%">
        <el-table-column label="名称" min-width="150">
          <template #default="{ row }">
            <p class="text-sm font-semibold text-stone-700">{{ row.name }}</p>
            <p class="text-xs text-stone-400">{{ row.description }}</p>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="绑定模型" min-width="150">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.model }}</code></template>
        </el-table-column>
        <el-table-column label="tokens" width="110" align="right">
          <template #default="{ row }">{{ fmtTokens(row.tokens) }}</template>
        </el-table-column>
        <el-table-column label="售价" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.price_yuan > 0">¥{{ row.price_yuan.toFixed(2) }}</span>
            <el-tag v-else size="small" effect="plain" type="info">仅赠送</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="有效期" width="90" align="center">
          <template #default="{ row }">{{ row.valid_days > 0 ? `${row.valid_days} 天` : '永久' }}</template>
        </el-table-column>
        <el-table-column label="发放/在用" width="100" align="center">
          <template #default="{ row }">{{ row.granted_count }} / {{ row.active_count }}</template>
        </el-table-column>
        <el-table-column label="已消耗" width="110" align="right">
          <template #default="{ row }">{{ fmtTokens(row.used_tokens) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.status === 1 ? 'success' : 'info'">
              {{ row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="openGrant(row)">发放</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 用户持有明细 -->
    <div class="mt-8 flex flex-wrap items-center justify-between gap-3">
      <h2 class="font-bold text-stone-800">用户持有明细</h2>
      <div class="flex flex-wrap items-center gap-2">
        <el-select v-model="filters.pack_id" placeholder="全部资源包" clearable class="!w-52" @change="() => { page = 1; loadGrants() }">
          <el-option v-for="p in defs" :key="p.id" :value="p.id" :label="p.name" />
        </el-select>
        <el-select v-model="filters.state" placeholder="全部状态" clearable class="!w-32" @change="() => { page = 1; loadGrants() }">
          <el-option v-for="s in ['active', 'expired', 'exhausted', 'disabled']" :key="s" :value="s"
            :label="{ active: '使用中', expired: '已到期', exhausted: '已用完', disabled: '已作废' }[s]" />
        </el-select>
        <el-input v-model="filters.search" placeholder="用户名 / UID" clearable class="!w-44"
          @keyup.enter="() => { page = 1; loadGrants() }" @clear="() => { page = 1; loadGrants() }" />
      </div>
    </div>
    <div class="mt-3 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="grants" style="width: 100%">
        <el-table-column label="用户" min-width="130">
          <template #default="{ row }">
            <p class="text-sm text-stone-700">{{ row.username }}</p>
            <p class="font-mono text-xs text-stone-400">{{ row.user_uid }}</p>
          </template>
        </el-table-column>
        <el-table-column label="资源包" min-width="140">
          <template #default="{ row }">
            <p class="text-sm text-stone-700">{{ row.pack_name }}</p>
            <code class="font-mono text-xs text-stone-400">{{ row.model }}</code>
          </template>
        </el-table-column>
        <el-table-column label="使用量" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.total_tokens ? Math.min(100, row.used_tokens / row.total_tokens * 100) : 0"
              :stroke-width="8" :show-text="false" />
            <p class="mt-1 text-xs text-stone-400">{{ fmtTokens(row.used_tokens) }} / {{ fmtTokens(row.total_tokens) }}</p>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="{ active: 'success', expired: 'info', exhausted: 'warning', disabled: 'danger' }[row.state]">
              {{ { active: '使用中', expired: '已到期', exhausted: '已用完', disabled: '已作废' }[row.state] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">{{ { register_gift: '注册赠送', admin_grant: '管理员发放' }[row.granted_type] || row.granted_type }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="获得时间" width="165" />
        <el-table-column label="到期时间" width="165">
          <template #default="{ row }">{{ row.expires_at || '永久' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button v-if="row.state === 'active'" link type="danger" @click="disableGrant(row)">作废</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="grantsTotal" :page-size="size"
        v-model:current-page="page" @current-change="loadGrants" />
    </div>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="edit.visible" :title="edit.form.id ? '编辑资源包' : '新建资源包'" width="480">
      <el-form label-position="top">
        <el-form-item label="名称" required>
          <el-input v-model="edit.form.name" maxlength="64" placeholder="如 GLM-5.3 体验包" />
        </el-form-item>
        <el-form-item label="绑定模型" required>
          <el-select v-model="edit.form.model" filterable placeholder="选择模型" class="!w-full">
            <el-option v-for="m in modelOptions" :key="m.name" :value="m.name"
              :label="`${m.display_name}(${m.name})`" />
          </el-select>
        </el-form-item>
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="tokens 数量(万)" required>
            <el-input-number v-model="edit.form.tokens_wan" :min="0.01" :precision="2" :step="10" class="!w-full" />
          </el-form-item>
          <el-form-item label="售价(CNY,0 = 仅赠送不可购买)">
            <el-input-number v-model="edit.form.price_yuan" :min="0" :precision="2" :step="10" class="!w-full" />
          </el-form-item>
          <el-form-item label="有效期(天,0=永久)">
            <el-input-number v-model="edit.form.valid_days" :min="0" :step="30" class="!w-full" />
          </el-form-item>
          <el-form-item label="排序(小的在前)">
            <el-input-number v-model="edit.form.sort" :min="0" class="!w-full" />
          </el-form-item>
          <el-form-item label="启用状态">
            <el-switch v-model="edit.form.status" active-text="启用" inactive-text="停用" />
          </el-form-item>
        </div>
        <el-form-item label="说明">
          <el-input v-model="edit.form.description" maxlength="200" placeholder="展示给用户的说明(可选)" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edit.visible = false">取消</el-button>
        <el-button type="primary" :loading="edit.saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 手动发放弹窗 -->
    <el-dialog v-model="grantDlg.visible" title="手动发放资源包" width="420">
      <p class="mb-3 text-sm text-stone-500">
        {{ grantDlg.pack?.name }} · {{ fmtTokens(grantDlg.pack?.tokens) }} tokens · {{ grantDlg.pack?.model }}
      </p>
      <el-form label-position="top">
        <el-form-item label="用户名或 UID" required>
          <el-input v-model="grantDlg.username" placeholder="目标用户的用户名或 UID(如 100003)" />
        </el-form-item>
        <el-form-item label="有效期(天,留空按定义)">
          <el-input-number v-model="grantDlg.validDays" :min="0" class="!w-full" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="grantDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="grantDlg.saving" @click="submitGrant">发放</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminCreateResourcePack, adminDeleteResourcePack, adminDisableResourcePackGrant,
  adminGetSettings, adminGrantResourcePack, adminPutSettings, adminResourcePackGrants,
  adminResourcePacks, adminUpdateResourcePack, getModelPrices,
} from '../../api'

const defs = ref([])
const grants = ref([])
const grantsTotal = ref(0)
const page = ref(1)
const size = 20
const modelOptions = ref([])
const filters = reactive({ pack_id: null, state: null, search: '' })
const gift = reactive({ enabled: false, packId: null, saving: false })
const edit = reactive({
  visible: false, saving: false,
  form: { id: null, name: '', model: '', tokens_wan: 100, price_yuan: 0, valid_days: 365, sort: 0, description: '', status: true },
})
const grantDlg = reactive({ visible: false, saving: false, pack: null, username: '', validDays: undefined })

function fmtTokens(n) {
  n = n || 0
  if (n >= 100_000_000) return (n / 100_000_000).toFixed(n % 100_000_000 ? 1 : 0) + ' 亿'
  if (n >= 10_000) return (n / 10_000).toFixed(n % 10_000 ? 1 : 0) + ' 万'
  return String(n)
}

async function loadDefs() {
  defs.value = (await adminResourcePacks()).data
}
async function loadGrants() {
  const res = await adminResourcePackGrants({
    page: page.value, page_size: size,
    pack_id: filters.pack_id || undefined,
    state: filters.state || undefined,
    search: filters.search || undefined,
  })
  grants.value = res.data.items
  grantsTotal.value = res.data.total
}

async function loadGiftSetting() {
  const s = (await adminGetSettings()).data
  gift.enabled = !!s.register_gift_pack_id
  gift.packId = s.register_gift_pack_id || null
}

async function saveGift() {
  gift.saving = true
  try {
    await adminPutSettings({ register_gift_pack_id: gift.enabled ? gift.packId : 0 })
    ElMessage.success('注册赠送设置已保存')
  } finally { gift.saving = false }
}

function openEdit(row) {
  edit.form = row
    ? { id: row.id, name: row.name, model: row.model,
        tokens_wan: Math.round(row.tokens / 100) / 100, price_yuan: row.price_yuan || 0,
        valid_days: row.valid_days, sort: row.sort, description: row.description, status: row.status === 1 }
    : { id: null, name: '', model: '', tokens_wan: 100, price_yuan: 0, valid_days: 365, sort: 0, description: '', status: true }
  edit.visible = true
}

async function saveEdit() {
  if (!edit.form.name?.trim() || !edit.form.model || !edit.form.tokens_wan) {
    ElMessage.warning('请填写名称、模型并填写 tokens 数量')
    return
  }
  edit.saving = true
  try {
    const payload = { ...edit.form, status: edit.form.status ? 1 : 0 }
    if (edit.form.id) await adminUpdateResourcePack(edit.form.id, payload)
    else await adminCreateResourcePack(payload)
    ElMessage.success('已保存')
    edit.visible = false
    await loadDefs()
  } finally { edit.saving = false }
}

async function remove(row) {
  await ElMessageBox.confirm(
    `确定删除资源包「${row.name}」?已有用户持有时无法删除,可改为停用。`, '删除确认', { type: 'warning' })
  await adminDeleteResourcePack(row.id)
  ElMessage.success('已删除')
  await loadDefs()
}

function openGrant(row) {
  grantDlg.pack = row
  grantDlg.username = ''
  grantDlg.validDays = undefined
  grantDlg.visible = true
}

async function submitGrant() {
  if (!grantDlg.username.trim()) {
    ElMessage.warning('请填写用户名')
    return
  }
  grantDlg.saving = true
  try {
    await adminGrantResourcePack(grantDlg.pack.id, {
      username: grantDlg.username.trim(),
      valid_days: grantDlg.validDays ?? undefined,
    })
    ElMessage.success('已发放')
    grantDlg.visible = false
    await Promise.all([loadDefs(), loadGrants()])
  } finally { grantDlg.saving = false }
}

async function disableGrant(row) {
  await ElMessageBox.confirm(
    `作废后 ${row.username} 的「${row.pack_name}」立即停止参与计费,不可恢复。`, '作废确认', { type: 'warning' })
  await adminDisableResourcePackGrant(row.id)
  ElMessage.success('已作废')
  await loadGrants()
}

onMounted(async () => {
  await loadDefs()
  await loadGrants()
  await loadGiftSetting()
  try {
    modelOptions.value = (await getModelPrices()).data
  } catch { /* 模型目录加载失败不阻塞 */ }
})
</script>
