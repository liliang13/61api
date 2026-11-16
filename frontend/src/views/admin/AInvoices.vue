<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">发票管理</h1>
    <div class="mt-4 flex gap-2">
      <el-radio-group v-model="statusFilter" @change="load">
        <el-radio-button :value="-1">全部</el-radio-button>
        <el-radio-button :value="0">待开具</el-radio-button>
        <el-radio-button :value="1">已开具</el-radio-button>
        <el-radio-button :value="2">已拒绝</el-radio-button>
      </el-radio-group>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="created_at" label="申请时间" width="150" />
        <el-table-column label="用户" min-width="140">
          <template #default="{ row }">
            <div class="text-xs font-semibold text-stone-700">{{ row.username }}</div>
            <div class="font-mono text-xs text-stone-400">{{ row.uid }} #{{ row.user_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="开票金额" width="110" align="right">
          <template #default="{ row }">¥{{ row.amount_yuan.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="inv_type" label="类型" width="130" />
        <el-table-column label="抬头 / 税号" min-width="200">
          <template #default="{ row }">
            <div class="text-xs font-semibold text-stone-700">{{ row.title }}</div>
            <div class="text-xs text-stone-400">{{ row.tax_no || row.title_type }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="接收邮箱" min-width="160" show-overflow-tooltip />
        <el-table-column label="关联订单" min-width="180">
          <template #default="{ row }">
            <code v-for="o in row.orders" :key="o.order_no" class="mr-1 font-mono text-xs text-stone-400">
              {{ o.order_no.slice(-8) }}
            </code>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="95" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.status === 2" :content="row.reject_reason" placement="top">
              <el-tag size="small" type="danger" effect="plain">已拒绝</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" effect="plain" :type="{ 0: 'warning', 1: 'success' }[row.status]">
              {{ { 0: '待开具', 1: '已开具' }[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发票号" width="140">
          <template #default="{ row }">{{ row.invoice_no || '-' }}</template>
        </el-table-column>
        <el-table-column label="发票文件" width="150" align="center">
          <template #default="{ row }">
            <a v-if="row.file_name" :href="`/api/admin/invoices/${row.id}/file`"
              class="text-sm font-semibold text-[#4f46e5] hover:underline">下载</a>
            <span v-else class="text-xs text-stone-300">未上传</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" align="center" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 0">
              <el-button link type="success" size="small" @click="openIssue(row)">开具</el-button>
              <el-button link type="danger" size="small" @click="reject(row)">拒绝</el-button>
            </template>
            <el-button link type="primary" size="small" @click="openUpload(row)">
              {{ row.file_name ? '重传' : '上传发票' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" />
    </div>
  </div>

    <!-- 上传发票文件 -->
    <el-dialog v-model="upl.visible" :title="`上传发票文件 · ${upl.row?.title || ''}`" width="440">
      <p class="mb-3 text-xs text-stone-400">
        {{ upl.row?.file_name ? `当前已上传:${upl.row.file_name}(重传将覆盖)` : '尚未上传发票文件' }}
      </p>
      <input ref="fileInput" type="file" accept=".pdf,application/pdf"
        @change="(e) => (upl.file = e.target.files[0] || null)"
        class="block w-full text-sm text-stone-600 file:mr-3 file:rounded-lg file:border-0
               file:bg-[#eef2ff] file:px-3 file:py-2 file:text-sm file:font-semibold file:text-[#4f46e5]
               hover:file:bg-[#e0e7ff]" />
      <p class="mt-2 text-xs text-stone-400">仅支持 PDF,大小不超过 10MB;上传后用户可在控制台下载</p>
      <template #footer>
        <el-button @click="upl.visible = false">取消</el-button>
        <el-button type="primary" :loading="upl.saving" :disabled="!upl.file" @click="doUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 开具发票弹窗(发票号 + 可选上传 PDF) -->
    <el-dialog v-model="issueDlg.visible" :title="`开具发票 · ${issueDlg.row?.title || ''}`" width="440"
      :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="发票号码" required>
          <el-input v-model="issueDlg.invoiceNo" maxlength="64" placeholder="填写发票号码" />
        </el-form-item>
        <el-form-item label="发票 PDF 文件(选填,上传后用户可自行下载)">
          <input type="file" accept=".pdf,application/pdf"
            @change="(e) => (issueDlg.file = e.target.files[0] || null)"
            class="block w-full text-sm text-stone-600 file:mr-3 file:rounded-lg file:border-0
                   file:bg-[#eef2ff] file:px-3 file:py-2 file:text-sm file:font-semibold file:text-[#4f46e5]
                   hover:file:bg-[#e0e7ff]" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueDlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="issueDlg.saving" @click="doIssue">确认开具</el-button>
      </template>
    </el-dialog>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminInvoices, adminIssueInvoice, adminRejectInvoice, adminUploadInvoiceFile } from '../../api'
import { dialogResult } from '../../utils/dialog'

const items = ref([])
const upl = reactive({ visible: false, row: null, file: null, saving: false })
const issueDlg = reactive({ visible: false, row: null, invoiceNo: '', file: null, saving: false })
const fileInput = ref(null)
const total = ref(0)
const page = ref(1)
const size = 20
const statusFilter = ref(-1)

async function load() {
  const params = { page: page.value, page_size: size }
  if (statusFilter.value !== -1) params.status = statusFilter.value
  const res = await adminInvoices(params)
  items.value = res.data.items
  total.value = res.data.total
}

function openIssue(row) {
  issueDlg.row = row
  issueDlg.invoiceNo = row.invoice_no || ''
  issueDlg.file = null
  issueDlg.visible = true
}

async function doIssue() {
  const no = issueDlg.invoiceNo.trim()
  if (!no) return ElMessage.warning('请填写发票号码')
  issueDlg.saving = true
  try {
    await adminIssueInvoice(issueDlg.row.id, no)
    if (issueDlg.file) {
      try {
        await adminUploadInvoiceFile(issueDlg.row.id, issueDlg.file)
        ElMessage.success('已开具并上传发票文件')
      } catch {
        ElMessage.warning('已开具,但发票文件上传失败,可在列表重传')
      }
    } else {
      ElMessage.success('已标记开具')
    }
    issueDlg.visible = false
    await load()
  } finally { issueDlg.saving = false }
}

async function reject(row) {
  const result = await dialogResult(ElMessageBox.prompt('拒绝原因(将展示给用户,拒绝后订单额度释放可重新申请):',
    `拒绝开票 · ${row.title}`, { confirmButtonText: '确认拒绝', cancelButtonText: '取消' }))
  if (!result) return
  await adminRejectInvoice(row.id, result.value.trim() || '信息有误')
  ElMessage.success('已拒绝,订单开票额度已释放')
  await load()
}

function openUpload(row) {
  upl.row = row
  upl.file = null
  upl.visible = true
}

async function doUpload() {
  if (!upl.file) return
  upl.saving = true
  try {
    await adminUploadInvoiceFile(upl.row.id, upl.file)
    ElMessage.success('发票文件已上传')
    upl.visible = false
    await load()
  } finally { upl.saving = false }
}

onMounted(load)
</script>
