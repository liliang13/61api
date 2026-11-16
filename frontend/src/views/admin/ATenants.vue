<template>
  <div>
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-xl font-bold text-stone-800">组织管理</h1>
        <p class="mt-1 text-sm text-stone-500">组织是额度、用户和用量的隔离边界;成员只能使用所属组织的额度。</p>
      </div>
      <el-button type="primary" @click="openCreate">新建组织</el-button>
    </div>

    <div class="mt-5 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="组织名称" min-width="160" />
        <el-table-column label="标识" min-width="120">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.slug }}</code></template>
        </el-table-column>
        <el-table-column prop="user_count" label="成员数" width="90" align="center" />
        <el-table-column label="剩余额度" width="130" align="right">
          <template #default="{ row }">
            <span v-if="row.quota < 0" class="font-semibold text-[#16a34a]">不限</span>
            <span v-else class="font-semibold text-stone-700">¥{{ (row.quota / 500000).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="累计消费" width="120" align="right">
          <template #default="{ row }">¥{{ row.usage_yuan.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.status === 1" @change="toggleStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" width="160" />
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dlg.visible" :title="dlg.id ? '编辑组织' : '新建组织'" width="460">
      <el-form label-position="top">
        <el-form-item label="组织名称">
          <el-input v-model="dlg.name" placeholder="如:研发中心" />
        </el-form-item>
        <el-form-item label="组织标识">
          <el-input v-model="dlg.slug" :disabled="!!dlg.id" placeholder="小写字母/数字/短横线,如 rd-center" />
        </el-form-item>
        <el-form-item label="剩余额度(CNY,-1 表示不限)">
          <el-input-number v-model="dlg.quota_yuan" :min="-1" :precision="2" class="!w-full" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="dlg.status" active-text="启用" inactive-text="停用" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dlg.note" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminCreateTenant, adminTenants, adminUpdateTenant } from '../../api'

const items = ref([])
const dlg = reactive({
  visible: false, id: null, name: '', slug: '', quota_yuan: -1, status: true, note: '', saving: false,
})

async function load() {
  items.value = (await adminTenants()).data
}

function openCreate() {
  Object.assign(dlg, { visible: true, id: null, name: '', slug: '', quota_yuan: -1, status: true, note: '', saving: false })
}

function openEdit(row) {
  Object.assign(dlg, {
    visible: true, id: row.id, name: row.name, slug: row.slug,
    quota_yuan: row.quota < 0 ? -1 : row.quota / 500000,
    status: row.status === 1, note: row.note || '', saving: false,
  })
}

async function toggleStatus(row) {
  await adminUpdateTenant(row.id, { status: row.status === 1 ? 0 : 1 })
  ElMessage.success('已更新')
  await load()
}

async function save() {
  dlg.saving = true
  try {
    if (dlg.id) {
      await adminUpdateTenant(dlg.id, {
        name: dlg.name,
        quota_set_yuan: dlg.quota_yuan,
        status: dlg.status ? 1 : 0,
        note: dlg.note,
      })
    } else {
      await adminCreateTenant({
        name: dlg.name,
        slug: dlg.slug,
        quota_yuan: dlg.quota_yuan,
        note: dlg.note,
      })
    }
    ElMessage.success('已保存')
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

onMounted(load)
</script>
