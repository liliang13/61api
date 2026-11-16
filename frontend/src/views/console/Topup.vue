<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">充值</h1>
    <p class="mt-2 text-xs text-stone-400">1 元 = 1 元额度 · 到账后可在充值记录中查询</p>

    <div v-if="methods.length" class="mt-4">
      <p class="mb-2 text-xs font-semibold text-stone-500">支付方式</p>
      <div class="flex gap-3">
        <div v-for="method in methods" :key="method" @click="payMethod = method"
          class="flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2.5"
          :class="payMethod === method ? methodClass(method).active : 'border-black/10 bg-white'">
          <span class="grid h-7 w-7 place-items-center rounded-lg text-xs font-bold text-white"
            :class="methodClass(method).badge">{{ method === 'alipay' ? '支' : '微' }}</span>
          <span class="text-sm font-semibold text-stone-700">{{ method === 'alipay' ? '支付宝' : '微信支付' }}</span>
        </div>
      </div>
    </div>

    <div v-if="!paykitReady" class="mt-6">
      <el-alert type="error" :closable="false" show-icon title="支付组件未就绪"
        description="未找到 paykit 模块,请检查 PAYKIT_PATH 配置。" />
    </div>

    <!-- 套餐 + 自定义金额 -->
    <div class="mt-5 flex flex-wrap gap-3">
      <div v-for="p in packages" :key="p.id" @click="selected = p"
        class="card-hover w-[168px] cursor-pointer rounded-xl border px-4 py-3"
        :class="selected?.id === p.id ? 'border-[#4f46e5] bg-[#eef2ff]/50 ring-2 ring-[#4f46e5]/20' : 'border-black/5 bg-white'">
        <p class="text-xs font-bold text-stone-700">{{ p.name }}</p>
        <div class="mt-1.5 flex items-center justify-between gap-1">
          <p class="text-xl font-bold text-stone-800">¥{{ p.price_yuan }}</p>
          <span v-if="p.bonus_pct > 0"
            class="rounded-full bg-gradient-to-r from-[#f97316] to-[#f59e0b] px-2 py-0.5 text-[11px] font-bold text-white shadow-sm">+{{ p.bonus_pct }}%</span>
        </div>
        <p class="mt-0.5 whitespace-nowrap text-xs text-stone-400">到账
          <span :class="p.bonus_pct > 0 ? 'font-bold text-[#ea580c]' : 'font-semibold text-stone-500'">¥{{ p.credits_yuan.toFixed(2) }}</span>
          额度
        </p>
      </div>
      <div v-if="customCfg.enabled" @click="selected = CUSTOM"
        class="card-hover w-[168px] cursor-pointer rounded-xl border px-4 py-3"
        :class="selected?.id === CUSTOM ? 'border-[#4f46e5] bg-[#eef2ff]/50 ring-2 ring-[#4f46e5]/20' : 'border-black/5 bg-white'">
        <p class="text-xs font-bold text-stone-700">自定义金额</p>
        <div class="mt-1 flex items-center gap-1" @click.stop="selected = CUSTOM">
          <span class="text-xl font-bold text-stone-800">¥</span>
          <el-input-number v-model="customYuan" :min="customCfg.min_yuan" :max="customCfg.max_yuan"
            :precision="2" :step="10" :controls="false" size="small" class="!w-24" />
        </div>
        <p class="mt-0.5 text-xs text-stone-400">{{ customCfg.min_yuan }} - {{ customCfg.max_yuan }} 元 · 到账 ¥{{ (customYuan || 0).toFixed(2) }} 额度</p>
        <p class="mt-1.5 inline-block rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-semibold text-[#ea580c]">无赠送优惠 · 按 1:1 到账</p>
      </div>
    </div>

    <div class="mt-4 text-xs text-stone-500">
      <!-- 文字放进插槽:点击行内任意位置均可切换勾选;协议链接单独拦截 -->
      <el-checkbox v-model="agree" class="!h-4 items-start">
        <span>
          我已阅读并同意
          <router-link to="/recharge-agreement" target="_blank" @click.stop
            class="font-semibold text-[#4f46e5] hover:underline">《充值协议》</router-link>
          ,知悉充值金额用于购买平台服务、不支持提现,且支付成功后非平台原因不予退款
        </span>
      </el-checkbox>
    </div>

    <el-button type="primary" size="large" class="mt-4 !px-10" :disabled="!selected || !payMethod || !paykitReady" :loading="creating" @click="createOrder">
      创建订单
    </el-button>

    <!-- 我的充值记录 -->
    <h2 class="mt-10 font-bold text-stone-800">充值记录</h2>
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="orders" style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="170" />
        <el-table-column prop="order_no" label="订单号" min-width="220">
          <template #default="{ row }"><code class="font-mono text-xs">{{ row.order_no }}</code></template>
        </el-table-column>
        <el-table-column label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.kind === 'resource_pack'" size="small" effect="plain" type="warning">资源包</el-tag>
            <el-tag v-else size="small" effect="plain">余额</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="金额" width="100" align="right">
          <template #default="{ row }">¥{{ (row.amount / 100).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="到账额度" width="110" align="right">
          <template #default="{ row }">¥{{ (row.quota / 500000).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="{ paid: 'success', pending: 'warning', refunded: 'info' }[row.status]">
              {{ { paid: '已到账', pending: '待支付', refunded: '已退款' }[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 收银台弹窗 -->
    <CashierDialog ref="cashierRef" v-model:visible="cashier.visible" :order-no="cashier.orderNo"
      :pay="cashier.pay" :method="cashier.method" @paid="handlePaid" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTopup, getPackages, getMyOrders } from '../../api'
import { useUserStore } from '../../stores/user'
import CashierDialog from '../../components/CashierDialog.vue'

const store = useUserStore()
const route = useRoute()
const router = useRouter()
const packages = ref([])
const selected = ref(null)
const customCfg = ref({ enabled: false, min_yuan: 1, max_yuan: 5000 })
const customYuan = ref(10)
const CUSTOM = { id: '__custom__' }
const orders = ref([])
const methods = ref([])
const paykitReady = ref(true)
const creating = ref(false)
const cashier = reactive({ visible: false, orderNo: '', pay: null, method: 'alipay' })
const payMethod = ref('')
const agree = ref(false)
const cashierRef = ref(null)

function methodClass(method) {
  return method === 'alipay'
    ? { active: 'border-[#1677ff] bg-[#f0f7ff]', badge: 'bg-[#1677ff]' }
    : { active: 'border-[#09bb07] bg-[#f0fbf0]', badge: 'bg-[#09bb07]' }
}

async function loadOrders() { orders.value = (await getMyOrders()).data }

function clearReturnQuery() {
  const query = { ...route.query }
  delete query.order
  delete query.done
  router.replace({ query })
}

async function handlePaid() {
  cashier.visible = false
  ElMessage.success('支付成功,额度已到账')
  await Promise.all([store.fetchMe(), loadOrders()])
  clearReturnQuery()
}

onMounted(async () => {
  const res = await getPackages()
  paykitReady.value = res.data.paykit
  methods.value = res.data.methods || []
  payMethod.value = methods.value[0] || ''
  packages.value = res.data.packages || []
  if (res.data.custom) customCfg.value = res.data.custom
  await loadOrders()
  const orderNo = Array.isArray(route.query.order) ? route.query.order[0] : route.query.order
  if (orderNo) cashierRef.value?.poll(orderNo)
})

async function createOrder() {
  if (!agree.value) return ElMessage.warning('请先阅读并勾选同意《充值协议》')
  if (selected.value.id === CUSTOM.id) {
    const yuan = Number(customYuan.value)
    if (!Number.isFinite(yuan) || yuan < customCfg.value.min_yuan || yuan > customCfg.value.max_yuan) {
      ElMessage.warning(`自定义金额需在 ¥${customCfg.value.min_yuan} - ¥${customCfg.value.max_yuan} 之间`)
      return
    }
  }
  creating.value = true
  try {
    const res = selected.value.id === CUSTOM.id
      ? await createTopup('custom', payMethod.value, Number(customYuan.value))
      : await createTopup(selected.value.id, payMethod.value)
    if (res.data.mode === 'sandbox' && !import.meta.env.DEV) {
      ElMessage.error('当前环境不支持沙箱支付')
      return
    }
    cashier.orderNo = res.data.order_no
    cashier.method = res.data.method || payMethod.value
    cashier.pay = { mode: res.data.mode, qr_content: res.data.qr_content, pay_url: res.data.pay_url }
    cashier.visible = true
    cashierRef.value?.poll(cashier.orderNo)
  } finally { creating.value = false }
}
</script>
