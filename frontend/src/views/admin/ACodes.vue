<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">兑换码</h1>
      <el-button type="primary" @click="dlg.visible = true">批量生成</el-button>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="code" label="兑换码" min-width="160">
          <template #default="{ row }"><code class="font-mono font-bold">{{ row.code }}</code></template>
        </el-table-column>
        <el-table-column label="面额" width="110" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="batch" label="批次" min-width="160" />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'" effect="plain">
              {{ row.status === 1 ? '未使用' : '已使用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="used_by" label="使用者" width="90" align="center">
          <template #default="{ row }">{{ row.used_by ? `#${row.used_by}` : '-' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="生成时间" width="165" />
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>

    <el-dialog v-model="dlg.visible" title="批量生成兑换码" width="440">
      <el-form label-position="top">
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="数量(1-500)"><el-input-number v-model="dlg.count" :min="1" :max="500" class="!w-full" /></el-form-item>
          <el-form-item label="每张面额(CNY)"><el-input-number v-model="dlg.yuan" :min="0.01" :precision="2" :step="1" class="!w-full" /></el-form-item>
        </div>
      </el-form>
      <div v-if="dlg.generated.length" class="max-h-40 overflow-y-auto rounded-lg bg-[#f5f5f5] p-3">
        <code v-for="c in dlg.generated" :key="c" class="mr-3 font-mono text-xs">{{ c }}</code>
      </div>
      <template #footer>
        <el-button v-if="dlg.generated.length" @click="copyAll">复制全部</el-button>
        <el-button @click="dlg.visible = false">关闭</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="generate">{{ dlg.generated.length ? '再生成一批' : '生成' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminCodes, adminGenCodes } from '../../api'
import { copyText } from '../../utils/clipboard'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 20
const dlg = reactive({ visible: false, count: 10, yuan: 1, saving: false, generated: [] })

async function load() {
  const res = await adminCodes({ page: page.value, page_size: size })
  items.value = res.data.items
  total.value = res.data.total
}

async function generate() {
  dlg.saving = true
  try {
    const res = await adminGenCodes({ count: dlg.count, yuan: dlg.yuan })
    dlg.generated = res.data.codes
    ElMessage.success(`已生成 ${res.data.count} 个兑换码`)
    await load()
  } finally { dlg.saving = false }
}

async function copyAll() {
  await copyText(dlg.generated.join('\n'), '已复制全部兑换码')
}

onMounted(load)
</script>
