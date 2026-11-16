<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">模型定价</h1>
      <div class="flex gap-2">
        <el-button :loading="savingOrder" @click="saveOrder">保存排序</el-button>
        <el-button type="primary" @click="openEdit(null)">新增模型</el-button>
      </div>
    </div>
    <p class="mt-2 text-xs text-stone-400">
      单价单位为 人民币 / 每百万 Tokens,用户看到的价格即此处设定值(折扣已含在内)。用上移/下移调整展示顺序(首页价格表、模型页、/v1/models 均按此顺序),改完点「保存排序」立即生效。
    </p>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="models" style="width: 100%">
        <el-table-column label="排序" width="110" align="center">
          <template #default="{ $index }">
            <el-button link size="small" :disabled="$index === 0" @click="moveRow($index, -1)">上移</el-button>
            <el-button link size="small" :disabled="$index === models.length - 1" @click="moveRow($index, 1)">下移</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="模型名" min-width="190">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.name }}</code></template>
        </el-table-column>
        <el-table-column prop="display_name" label="显示名" min-width="140" />
        <el-table-column prop="vendor" label="厂商" width="100" />
        <el-table-column label="输入 ¥/1M" width="110" align="right">
          <template #default="{ row }">{{ row.input_price.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="输出 ¥/1M" width="110" align="right">
          <template #default="{ row }">{{ row.output_price.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="上架" width="80" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.status === 1" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dlg.visible" :title="dlg.editId ? '编辑模型' : '新增模型'" width="560">
      <el-form label-position="top">
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="模型名(调用时使用)"><el-input v-model="dlg.form.name" /></el-form-item>
          <el-form-item label="显示名"><el-input v-model="dlg.form.display_name" /></el-form-item>
        </div>
        <div class="grid grid-cols-3 gap-3">
          <el-form-item label="厂商"><el-input v-model="dlg.form.vendor" /></el-form-item>
          <el-form-item label="输入价 ¥/1M"><el-input-number v-model="dlg.form.input_price" :min="0" :precision="4" :step="0.05" class="!w-full" /></el-form-item>
          <el-form-item label="输出价 ¥/1M"><el-input-number v-model="dlg.form.output_price" :min="0" :precision="4" :step="0.05" class="!w-full" /></el-form-item>
        </div>
        <div class="grid grid-cols-1 gap-3">
          <el-form-item label="缓存命中输入价 ¥/1M(0 = 不区分,缓存命中也按全价)">
            <el-input-number v-model="dlg.form.cache_input_price" :min="0" :precision="4" :step="0.05" class="!w-full" />
          </el-form-item>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="官方原价 输入¥/1M(0=不展示折扣)"><el-input-number v-model="dlg.form.official_input" :min="0" :precision="3" :step="0.5" class="!w-full" /></el-form-item>
          <el-form-item label="官方原价 输出¥/1M(0=不展示折扣)"><el-input-number v-model="dlg.form.official_output" :min="0" :precision="3" :step="0.5" class="!w-full" /></el-form-item>
        </div>
        <el-form-item label="标签(逗号分隔)">
          <el-input v-model="tagsText" placeholder="对话, 推理, 编码" />
        </el-form-item>
        <el-form-item label="排序(小者靠前)"><el-input-number v-model="dlg.form.sort" class="!w-40" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminCreateModel, adminDeleteModel, adminModels, adminReorderModels, adminUpdateModel } from '../../api'
import { dialogResult } from '../../utils/dialog'

const models = ref([])
const savingOrder = ref(false)
const dlg = reactive({
  visible: false, editId: null, saving: false,
  form: { name: '', display_name: '', vendor: '', input_price: 0, output_price: 0, cache_input_price: 0, official_input: 0, official_output: 0, tags: [], sort: 0 },
})
const tagsText = computed({
  get: () => (dlg.form.tags || []).join(', '),
  set: (v) => { dlg.form.tags = v.split(/[,，]+/).map((s) => s.trim()).filter(Boolean) },
})

async function load() { models.value = (await adminModels()).data }

function moveRow(index, delta) {
  const target = index + delta
  if (target < 0 || target >= models.value.length) return
  const [row] = models.value.splice(index, 1)
  models.value.splice(target, 0, row)
}

async function saveOrder() {
  savingOrder.value = true
  try {
    await adminReorderModels(models.value.map((m) => m.id))
    ElMessage.success('排序已保存,前台列表即时生效')
  } finally { savingOrder.value = false }
}

function openEdit(row) {
  dlg.editId = row?.id || null
  dlg.form = row ? { cache_input_price: 0, ...row } : { name: '', display_name: '', vendor: '', input_price: 0, output_price: 0, cache_input_price: 0, official_input: 0, official_output: 0, tags: [], sort: 0 }
  dlg.visible = true
}

async function save() {
  if (!dlg.form.name) return ElMessage.warning('请填写模型名')
  dlg.saving = true
  try {
    if (dlg.editId) await adminUpdateModel(dlg.editId, dlg.form)
    else await adminCreateModel(dlg.form)
    ElMessage.success('已保存')
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

async function toggle(row) {
  await adminUpdateModel(row.id, { status: row.status === 1 ? 0 : 1 })
  await load()
}

async function remove(row) {
  if (!await dialogResult(ElMessageBox.confirm(`确定删除模型「${row.name}」?`, '删除确认', { type: 'warning' }))) return
  await adminDeleteModel(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>
