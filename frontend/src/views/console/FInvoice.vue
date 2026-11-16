<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">发票管理</h1>
    <p class="mt-2 text-xs text-stone-400">
      按充值订单金额开票,可多单合并;电子发票将发送至预留邮箱。<b class="text-stone-500">已申请开票的订单不可退款。</b>
    </p>

    <!-- 可开票订单(主页平铺勾选) -->
    <h2 class="mt-6 text-sm font-bold text-stone-700">可开票订单</h2>
    <p class="mt-1 text-xs text-stone-400">勾选要开票的已支付订单(金额为订单全额,可多选合并一张发票):</p>
    <div class="mt-3 max-w-4xl overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table ref="orderTable" :data="orders"
        :header-cell-style="{ padding: '14px 0' }"
        :cell-style="{ padding: '16px 0' }"
        @row-click="onOrderRowClick"
        @selection-change="(rows) => (selectedOrders = rows)">
        <el-table-column type="selection" width="48" />
        <el-table-column prop="order_no" label="订单号" min-width="260">
          <template #default="{ row }"><code class="font-mono text-sm">{{ row.order_no }}</code></template>
        </el-table-column>
        <el-table-column prop="created_at" label="日期" width="150" />
        <el-table-column label="可开票金额" width="150" align="right">
          <template #default="{ row }">
            <span class="text-sm font-bold text-stone-700">¥{{ row.invoicable_yuan.toFixed(2) }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!orders.length" description="暂无可开票的已支付订单" :image-size="70" />
    </div>
    <div class="mt-4 flex max-w-4xl items-center justify-between">
      <p class="text-sm text-stone-500">
        合计开票金额:<b class="text-base text-[#4f46e5]">¥{{ selectedTotal.toFixed(2) }}</b>
      </p>
      <el-button type="primary" :disabled="!selectedOrders.length" @click="openApply">申请开票</el-button>
    </div>

    <!-- 开票记录 -->
    <h2 class="mt-8 text-sm font-bold text-stone-700">开票记录</h2>
    <div class="mt-3 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="items" style="width: 100%">
        <el-table-column prop="created_at" label="申请时间" width="150" />
        <el-table-column label="开票金额" width="110" align="right">
          <template #default="{ row }">¥{{ row.amount_yuan.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="inv_type" label="类型" width="130" />
        <el-table-column label="抬头" min-width="180">
          <template #default="{ row }">
            <div class="text-xs font-semibold text-stone-700">{{ row.title }}</div>
            <div class="text-xs text-stone-400">{{ row.title_type }}{{ row.tax_no ? ' · ' + row.tax_no : '' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="关联订单" min-width="200">
          <template #default="{ row }">
            <code v-for="o in row.orders" :key="o.order_no" class="mr-1 font-mono text-xs text-stone-400">
              {{ o.order_no.slice(-8) }}(¥{{ o.amount_yuan.toFixed(2) }})
            </code>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="95" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.status === 2" :content="row.reject_reason" placement="top">
              <el-tag size="small" type="danger" effect="plain">已拒绝</el-tag>
            </el-tooltip>
            <el-tag v-else size="small" effect="plain" :type="{ 0: 'warning', 1: 'success' }[row.status]">
              {{ { 0: '开具中', 1: '已开具' }[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发票号" width="150">
          <template #default="{ row }">{{ row.invoice_no || '-' }}</template>
        </el-table-column>
        <el-table-column label="发票文件" width="120" align="center">
          <template #default="{ row }">
            <a v-if="row.file_name" :href="`/api/user/invoices/${row.id}/file`"
              class="text-sm font-semibold text-[#4f46e5] hover:underline">下载 PDF</a>
            <span v-else class="text-xs text-stone-300">-</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!items.length" description="暂无开票记录" />
    </div>

    <!-- 开票弹窗(表单) -->
    <el-dialog v-model="dlg.visible" title="申请开票" width="560" class="invoice-dialog">
      <p class="mb-3 rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
        已选 {{ dlg.orders.length }} 笔订单 · 合计开票金额
        <b>¥{{ dlg.orders.reduce((s, o) => s + o.invoicable_yuan, 0).toFixed(2) }}</b>
      </p>
      <el-form label-position="top">
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="发票类型">
            <el-select v-model="dlg.form.inv_type" class="w-full">
              <el-option label="电子普通发票" value="电子普通发票" />
              <el-option label="增值税专用发票" value="增值税专用发票" />
            </el-select>
          </el-form-item>
          <el-form-item label="抬头类型">
            <el-radio-group v-model="dlg.form.title_type">
              <el-radio value="企业">企业</el-radio>
              <el-radio v-if="dlg.form.inv_type !== '增值税专用发票'" value="个人">个人</el-radio>
            </el-radio-group>
          </el-form-item>
        </div>
        <el-form-item label="发票抬头">
          <el-input v-model="dlg.form.title" :placeholder="dlg.form.title_type === '企业' ? '企业全称' : '个人姓名'" />
        </el-form-item>
        <el-form-item v-if="dlg.form.title_type === '企业'" label="税号(统一社会信用代码)">
          <el-input v-model="dlg.form.tax_no" maxlength="18" placeholder="18 位统一社会信用代码" />
        </el-form-item>
        <p class="mb-3 flex flex-col items-start gap-1.5 text-xs">
          <span class="rounded bg-stone-100 px-2 py-1 text-stone-600">发票项目:信息技术服务费</span>
          <span class="rounded bg-stone-100 px-2 py-1 text-stone-600">税率:6%</span>
        </p>
        <el-form-item label="接收邮箱">
          <el-input v-model="dlg.form.email" placeholder="电子发票将发送至此邮箱" />
        </el-form-item>
        <el-form-item label="备注(选填)">
          <el-input v-model="dlg.form.remark" type="textarea" :rows="2" maxlength="200" />
        </el-form-item>
        <template v-if="dlg.form.inv_type === '增值税专用发票'">
          <div class="flex items-start gap-2 rounded-xl border p-3"
            :class="dlg.specialConfirmed ? 'border-[#16a34a]/30 bg-[#f0fdf4]' : 'border-amber-200 bg-amber-50'">
            <el-checkbox v-model="dlg.specialConfirmed" :disabled="!confirmReadDone"
              class="!mt-0.5 items-start" />
            <span class="text-xs leading-5 text-stone-600">
              我已阅读并同意<a class="cursor-pointer font-semibold text-[#4f46e5] underline"
                @click="openConfirmDialog">《专用发票抬头确认书》</a>,确认仅就我司实际购买商品或服务索取专用发票
              <el-tag v-if="dlg.specialConfirmed" size="small" type="success" effect="plain" class="ml-1">已确认</el-tag>
            </span>
          </div>
        </template>
      </el-form>
      <el-alert type="warning" :closable="false" show-icon class="mt-2" title="开票后该部分充值金额不可退款" />
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" :disabled="!dlg.orders.length" @click="submit">提交申请</el-button>
      </template>
    </el-dialog>

    <!-- 专用发票抬头确认书阅读弹窗:滚动到底才能同意 -->
    <el-dialog v-model="confirmDlg" title="专用发票抬头确认书" width="600" append-to-body
      class="confirm-dialog" :close-on-click-modal="false">
      <div ref="confirmScroll" @scroll="onConfirmScroll"
        class="max-h-[46vh] overflow-y-auto rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-6 text-stone-600">
        <p>根据国家税法及发票管理相关规定,任何单位和个人不得要求他人为自己开具与实际经营业务情况不符的专用发票【包括并不限于(1) 在没有货物采购或者没有接受应税劳务的情况下要求他人为自己开具专用发票; (2) 虚有货物采购或者接受应税劳务但要求他人为自己开具数量或金额与实际情况不符的专用发票】, 否则属于"虚开专用发票"。</p>
        <p class="mt-3">我已充分了解上述各项相关国家税法和发票管理规定,<b>并确认仅就我司实际购买商品或服务索取发票</b>。如我司未按国家相关规定申请开具或使用专用发票,由我司自行承担相应法律后果。</p>
      </div>
      <template #footer>
        <el-button @click="confirmDlg = false">取消</el-button>
        <el-button type="primary" :disabled="!confirmReadDone" @click="agreeConfirmation">我已阅读完毕,同意并勾选</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createInvoice, getInvoiceOrders, getMyInvoices } from '../../api'

const items = ref([])
const orders = ref([])
const selectedOrders = ref([])
const selectedTotal = computed(() => selectedOrders.value.reduce((s, o) => s + o.invoicable_yuan, 0))
const dlg = reactive({
  visible: false, orders: [], saving: false,
  form: { inv_type: '电子普通发票', title_type: '企业', title: '', tax_no: '', email: '', remark: '' },
  specialConfirmed: false,
})
const confirmDlg = ref(false)
const confirmReadDone = ref(false)
const confirmScroll = ref(null)

function checkReadToBottom() {
  const el = confirmScroll.value
  if (!el) return
  // 内容未超出可视区(无需滚动)直接视为已读完;超出则需滚动到底
  if (el.scrollHeight <= el.clientHeight + 8) confirmReadDone.value = true
}

function openConfirmDialog() {
  confirmReadDone.value = false
  confirmDlg.value = true
  nextTick(() => {
    const el = confirmScroll.value
    if (!el) return
    el.scrollTop = 0
    checkReadToBottom()
  })
}

function onConfirmScroll(e) {
  const el = e.target
  if (el.scrollTop + el.clientHeight >= el.scrollHeight - 8) {
    confirmReadDone.value = true
  }
}

function agreeConfirmation() {
  dlg.specialConfirmed = true
  confirmDlg.value = false
  ElMessage.success('已同意《专用发票抬头确认书》')
}


// 点击行内任意位置切换勾选;点勾选框本身时 EP 已处理,跳过防二次切换
const orderTable = ref(null)
function onOrderRowClick(row, column, event) {
  if (event && event.target && event.target.closest('.el-checkbox')) return
  orderTable.value?.toggleRowSelection(row)
}

async function load() {
  const [inv, ord] = await Promise.all([
    getMyInvoices().then((r) => r.data),
    getInvoiceOrders().then((r) => r.data),
  ])
  items.value = inv
  orders.value = ord
  selectedOrders.value = []
}

function openApply() {
  if (!selectedOrders.value.length) {
    ElMessage.info('请先勾选要开票的订单')
    return
  }
  dlg.orders = selectedOrders.value
  dlg.form = { inv_type: '电子普通发票', title_type: '企业', title: '', tax_no: '', email: '', remark: '' }
  dlg.specialConfirmed = false
  confirmReadDone.value = false
  dlg.visible = true
}

// 专票仅支持企业抬头:切到专票时个人自动切回企业
watch(() => dlg.form.inv_type, (v) => {
  if (v === '增值税专用发票' && dlg.form.title_type === '个人') dlg.form.title_type = '企业'
})

async function submit() {
  const f = dlg.form
  if (!f.title) return ElMessage.warning('请填写发票抬头')
  if (f.title_type === '企业' && !/^[0-9A-HJ-NPQRTUWXY]{18}$/.test(f.tax_no))
    return ElMessage.warning('请填写 18 位统一社会信用代码')
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) return ElMessage.warning('请填写正确的接收邮箱')
  if (f.inv_type === '增值税专用发票' && !dlg.specialConfirmed)
    return ElMessage.warning('申请专票请先阅读并同意《专用发票抬头确认书》')
  dlg.saving = true
  try {
    await createInvoice({
      order_nos: dlg.orders.map((o) => o.order_no),
      inv_type: f.inv_type, title_type: f.title_type,
      title: f.title, tax_no: f.tax_no, email: f.email, remark: f.remark,
      special_confirmation: f.inv_type === '增值税专用发票',
    })
    ElMessage.success('开票申请已提交,开具后将发送至邮箱')
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

onMounted(load)
</script>
