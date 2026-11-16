<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <button v-for="s in statusTabs" :key="s.value" @click="selectStatus(s.value)"
          class="rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors"
          :class="status === s.value
            ? 'border-[#4f46e5] bg-[#4f46e5] text-white'
            : 'border-black/10 bg-white text-stone-600 hover:border-[#4f46e5]/40 hover:text-[#4f46e5]'">
          {{ s.label }}<span v-if="s.value" class="ml-1 text-xs opacity-70">{{ countOf(s.value) }}</span>
        </button>
      </div>
      <el-button type="primary" @click="openCreate">新建工单</el-button>
    </div>

    <div class="mt-5 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%" @row-click="(row) => $router.push(`/console/tickets/${row.id}`)"
        class="cursor-pointer">
        <el-table-column label="标题" min-width="240">
          <template #default="{ row }">
            <div class="flex items-center gap-2">
              <span class="min-w-0 flex-1 truncate font-semibold text-stone-800">{{ row.title }}</span>
              <span class="shrink-0 text-xs text-stone-400">{{ row.preview }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="140" />
        <el-table-column prop="updated_at" label="最后更新" width="140" />
      </el-table>
      <el-empty v-if="!items.length" description="暂无工单" />
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" hide-on-single-page />
    </div>

    <el-dialog v-model="createDlg.visible" title="新建工单" width="520">
      <el-form label-position="top">
        <el-form-item label="标题" required>
          <el-input v-model="createDlg.title" maxlength="128" placeholder="一句话描述问题" show-word-limit />
        </el-form-item>
        <el-form-item label="详细描述" required>
          <el-input v-model="createDlg.content" type="textarea" :rows="6" maxlength="5000"
            placeholder="请描述问题现象、发生时间、相关订单号或模型名等,我们会尽快处理" show-word-limit />
        </el-form-item>
        <el-form-item label="截图附件(选填,PNG/JPG/WebP/GIF,≤5MB)">
          <div class="w-full">
            <input type="file" accept="image/png,image/jpeg,image/webp,image/gif"
              @change="onFileChange" class="block w-full text-sm text-stone-600
              file:mr-3 file:rounded-lg file:border-0 file:bg-[#eef2ff] file:px-3 file:py-2
              file:text-sm file:font-semibold file:text-[#4f46e5] hover:file:bg-[#e0e7ff]" />
            <p v-if="createDlg.error" class="mt-1 text-xs text-[#ef4444]">{{ createDlg.error }}</p>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="createDlg.saving" @click="submitCreate">提交工单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createTicket, getMyTickets, uploadTicketAttachment } from '../../api'

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
const createDlg = ref({ visible: false, title: '', content: '', file: null, error: '', saving: false })

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
  const res = await getMyTickets({ page: page.value, page_size: size, status: status.value || undefined })
  items.value = res.data?.items || []
  total.value = res.data?.total || 0
  counts.value = {}
  for (const s of ['open', 'answered', 'closed']) {
    if (s === status.value) counts.value[s] = total.value
  }
}

function openCreate() {
  createDlg.value = { visible: true, title: '', content: '', file: null, error: '', saving: false }
}

function onFileChange(e) {
  const f = e.target.files[0] || null
  createDlg.value.error = ''
  if (!f) { createDlg.value.file = null; return }
  if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(f.type)) {
    e.target.value = ''
    createDlg.value.error = '仅支持 PNG/JPG/WebP/GIF 图片'
    return
  }
  if (f.size > 5 * 1024 * 1024) {
    e.target.value = ''
    createDlg.value.error = '图片大小不能超过 5MB'
    return
  }
  createDlg.value.file = f
}

async function submitCreate() {
  const d = createDlg.value
  if (!d.title.trim()) return ElMessage.warning('请填写标题')
  if (!d.content.trim()) return ElMessage.warning('请填写详细描述')
  d.saving = true
  try {
    let attachment
    if (d.file) {
      try {
        attachment = (await uploadTicketAttachment(d.file)).data
      } catch (e) {
        return ElMessage.error(e.response?.data?.error || '附件上传失败')
      }
    }
    await createTicket({
      title: d.title.trim(), content: d.content.trim(),
      attachment: attachment ? { key: attachment.key, name: attachment.name, size: attachment.size } : undefined,
    })
    ElMessage.success('工单已提交,我们会尽快处理')
    d.visible = false
    status.value = ''
    page.value = 1
    await load()
  } finally { d.saving = false }
}

onMounted(load)
</script>
