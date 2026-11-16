<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">API 密钥</h1>
      <el-button type="primary" @click="openCreate">新建密钥</el-button>
    </div>
    <p class="mt-2 text-xs text-stone-400">
      密钥用于调用 /v1 接口。<b class="text-stone-500">完整密钥仅在创建时展示一次</b>,关闭弹窗后无法再次查看;遗忘请删除重建。
    </p>

    <div class="mt-5 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="keys" style="width: 100%">
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="密钥" min-width="200">
          <template #default="{ row }">
            <code class="font-mono text-xs text-stone-500">{{ row.key_masked }}</code>
          </template>
        </el-table-column>
        <el-table-column label="额度" width="160">
          <template #default="{ row }">
            {{ row.quota_limit < 0 ? '不限' : `¥${(row.quota_limit / 500000).toFixed(6)}` }}
            <span class="text-xs text-stone-400">已用 ¥{{ (row.used_quota / 500000).toFixed(6) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-switch :model-value="row.status === 1" @change="toggleStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="140" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="removeKey(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="dlg.visible" :title="dlg.title" width="440">
      <el-form label-position="top">
        <el-form-item label="密钥名称">
          <el-input v-model="dlg.form.name" placeholder="如:生产环境 / 本地开发" maxlength="64" />
        </el-form-item>
        <el-form-item label="额度上限(元,留空为不限)">
          <el-input-number v-model="dlg.form.limit_yuan" :min="0" :precision="2" :step="1" class="!w-full" placeholder="不限" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="save">确定</el-button>
      </template>
    </el-dialog>

    <!-- 新建成功展示完整密钥(仅此一次) -->
    <el-dialog v-model="created.visible" title="密钥创建成功" width="500" :close-on-click-modal="false"
      :show-close="false" :before-close="confirmCloseCreated">
      <el-alert type="warning" :closable="false" show-icon class="mb-4"
        title="完整密钥仅此一次展示,关闭后将无法再次查看!" />
      <code class="block break-all rounded-lg bg-[#1e1e2e] p-4 font-mono text-sm text-[#a5d6ff]">{{ created.key }}</code>
      <p class="mt-2 text-center text-xs text-stone-400">请立即复制并妥善保存(如密码管理器);若遗忘,删除该密钥重新创建即可。</p>
      <template #footer>
        <el-button @click="confirmCloseCreated">我已保存,关闭</el-button>
        <el-button type="primary" @click="copyCreated">复制密钥</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createKey, deleteKey, getKeys, updateKey } from '../../api'
import { copyText } from '../../utils/clipboard'
import { dialogResult } from '../../utils/dialog'

const keys = ref([])
const dlg = reactive({ visible: false, title: '新建密钥', saving: false, editId: null, form: { name: '', limit_yuan: undefined } })
const created = reactive({ visible: false, key: '', copied: false })

async function load() { keys.value = (await getKeys()).data }

function openCreate() {
  dlg.title = '新建密钥'
  dlg.editId = null
  dlg.form = { name: '', limit_yuan: undefined }
  dlg.visible = true
}

async function save() {
  dlg.saving = true
  try {
    if (dlg.editId) {
      await updateKey(dlg.editId, { name: dlg.form.name, limit_yuan: dlg.form.limit_yuan })
      ElMessage.success('已保存')
    } else {
      const res = await createKey({ name: dlg.form.name || '默认密钥', limit_yuan: dlg.form.limit_yuan })
      created.key = res.data.key
      created.copied = false
      created.visible = true
    }
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

async function copyCreated() {
  if (await copyText(created.key, '已复制到剪贴板')) created.copied = true
}

function confirmCloseCreated() {
  if (!created.copied) {
    ElMessageBox.confirm('尚未复制密钥,关闭后将无法再次查看。确定关闭?', '请确认已保存', {
      confirmButtonText: '确定关闭', cancelButtonText: '再看看', type: 'warning',
    }).then(() => { created.visible = false }).catch(() => {})
    return
  }
  created.visible = false
}

async function toggleStatus(row) {
  await updateKey(row.id, { status: row.status === 1 ? 0 : 1 })
  ElMessage.success(row.status === 1 ? '已禁用' : '已启用')
  await load()
}

async function removeKey(row) {
  if (!await dialogResult(ElMessageBox.confirm(`确定删除密钥「${row.name}」?删除后使用该密钥的调用将立即失败。`, '删除确认', { type: 'warning' }))) return
  await deleteKey(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
