<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">资源包</h1>
    <p class="mt-2 text-xs text-stone-400">模型专属 tokens 包 · 调用绑定模型时优先消耗包内 tokens(不计费)· 用尽或到期后自动回落余额计费</p>

    <!-- 可购资源包 -->
    <template v-if="store.feature('payments')">
      <div v-if="!paykitReady" class="mt-5">
        <el-alert type="error" :closable="false" show-icon title="支付组件未就绪"
          description="未找到 paykit 模块,请检查 PAYKIT_PATH 配置。" />
      </div>
      <div v-else-if="offers.length" class="mt-5">
        <div v-if="methods.length" class="mb-3">
          <p class="mb-2 text-xs font-semibold text-stone-500">支付方式</p>
          <div class="flex gap-3">
            <div v-for="m in methods" :key="m" @click="payMethod = m"
              class="flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2.5"
              :class="payMethod === m ? methodClass(m).active : 'border-black/10 bg-white'">
              <span class="grid h-7 w-7 place-items-center rounded-lg text-xs font-bold text-white"
                :class="methodClass(m).badge">{{ m === 'alipay' ? '支' : '微' }}</span>
              <span class="text-sm font-semibold text-stone-700">{{ m === 'alipay' ? '支付宝' : '微信支付' }}</span>
            </div>
          </div>
        </div>
        <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div v-for="p in offers" :key="p.id"
            class="card-hover flex cursor-pointer flex-col rounded-2xl border border-black/5 bg-white p-5"
            @click="buy(p)">
            <p class="text-sm font-bold text-stone-700">{{ p.name }}</p>
            <p class="mt-1 truncate font-mono text-xs text-stone-400">{{ p.model }}</p>
            <p class="mt-3 text-2xl font-bold text-[#4f46e5]">¥{{ p.price_yuan }}</p>
            <p class="mt-1 text-xs text-stone-500">{{ fmtTokens(p.tokens) }} tokens · {{ p.valid_days > 0 ? `${p.valid_days} 天有效` : '永久有效' }}</p>
            <el-button type="primary" size="small" class="mt-4" :disabled="!payMethod">立即购买</el-button>
          </div>
        </div>
      </div>
      <div class="mt-4 text-xs text-stone-500">
        <!-- 文字放进插槽:点击行内任意位置均可切换勾选;协议链接单独拦截 -->
        <el-checkbox v-model="agree" class="!h-4 items-start">
          <span>
            我已阅读并同意
            <router-link to="/recharge-agreement" target="_blank" @click.stop
              class="font-semibold text-[#4f46e5] hover:underline">《充值协议》</router-link>
            ,知悉资源包为预付服务、不支持提现,且支付成功后非平台原因不予退款
          </span>
        </el-checkbox>
      </div>
    </template>

    <!-- 我的资源包 -->
    <h2 class="mt-10 font-bold text-stone-800">我的资源包</h2>
    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="packs" style="width: 100%">
        <el-table-column label="资源包" min-width="160">
          <template #default="{ row }">
            <p class="text-sm font-semibold text-stone-700">{{ row.pack_name }}</p>
            <p class="font-mono text-xs text-stone-400">{{ row.model }}</p>
          </template>
        </el-table-column>
        <el-table-column label="总量" width="120" align="right">
          <template #default="{ row }">{{ fmtTokens(row.total_tokens) }}</template>
        </el-table-column>
        <el-table-column label="使用量" min-width="180">
          <template #default="{ row }">
            <el-progress :percentage="row.total_tokens ? Math.min(100, row.used_tokens / row.total_tokens * 100) : 0"
              :stroke-width="8" :show-text="false"
              :status="row.state === 'exhausted' ? 'success' : undefined" />
            <p class="mt-1 text-xs text-stone-400">已用 {{ fmtTokens(row.used_tokens) }} / 剩 {{ fmtTokens(row.remaining_tokens) }}</p>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="stateType(row.state)">{{ stateText(row.state) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">{{ sourceText(row.granted_type) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="获得时间" width="165" />
        <el-table-column label="到期时间" width="165">
          <template #default="{ row }">{{ row.expires_at || '永久' }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!packs.length" description="暂无资源包;可购买或等待注册赠送/管理员发放" :image-size="80" />
    </div>

    <!-- 收银台弹窗 -->
    <CashierDialog ref="cashierRef" v-model:visible="cashier.visible" :order-no="cashier.orderNo"
      :pay="cashier.pay" :method="cashier.method" @paid="handlePaid" />
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createTopup, getMyResourcePacks, getPackages, getResourcePackOffers,
} from '../../api'
import { useUserStore } from '../../stores/user'
import CashierDialog from '../../components/CashierDialog.vue'

const store = useUserStore()
const offers = ref([])
const packs = ref([])
const methods = ref([])
const payMethod = ref('')
const agree = ref(false)
const paykitReady = ref(true)
const cashier = reactive({ visible: false, orderNo: '', pay: null, method: 'alipay' })
const cashierRef = ref(null)

function fmtTokens(n) {
  n = n || 0
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(n % 1_000_000 ? 2 : 0) + 'M'
  if (n >= 10_000) return (n / 10_000).toFixed(n % 10_000 ? 1 : 0) + '万'
  return String(n)
}

function methodClass(m) {
  return m === 'alipay'
    ? { active: 'border-[#1677ff] bg-[#f0f7ff]', badge: 'bg-[#1677ff]' }
    : { active: 'border-[#09bb07] bg-[#f0fbf0]', badge: 'bg-[#09bb07]' }
}

function stateText(state) {
  return { active: '使用中', expired: '已到期', exhausted: '已用完', disabled: '已作废' }[state] || state
}
function stateType(state) {
  return { active: 'success', expired: 'info', exhausted: 'warning', disabled: 'danger' }[state] || 'info'
}
function sourceText(type) {
  return { purchase: '购买', register_gift: '注册赠送', admin_grant: '管理员发放' }[type] || type
}

async function loadPacks() { packs.value = (await getMyResourcePacks()).data }

async function buy(p) {
  if (!agree.value) return ElMessage.warning('请先阅读并勾选同意《充值协议》')
  try {
    const res = await createTopup(p.id, payMethod.value)
    if (res.data.mode === 'sandbox' && !import.meta.env.DEV) {
      ElMessage.error('当前环境不支持沙箱支付')
      return
    }
    cashier.orderNo = res.data.order_no
    cashier.method = res.data.method || payMethod.value
    cashier.pay = { mode: res.data.mode, qr_content: res.data.qr_content, pay_url: res.data.pay_url }
    cashier.visible = true
    cashierRef.value?.poll(cashier.orderNo)
  } catch { /* 错误提示由 http 拦截器统一处理 */ }
}

async function handlePaid() {
  cashier.visible = false
  ElMessage.success('支付成功,资源包已到账')
  await loadPacks()
}

onMounted(async () => {
  await loadPacks()
  if (!store.feature('payments')) return
  try {
    const res = await getResourcePackOffers()
    offers.value = res.data.items || []
    paykitReady.value = res.data.purchasable !== false
  } catch { paykitReady.value = false }
  try {
    const res = await getPackages()
    methods.value = res.data.methods || []
    payMethod.value = methods.value[0] || ''
  } catch { /* 支付方式加载失败不阻塞页面 */ }
})
</script>
