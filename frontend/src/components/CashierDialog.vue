<template>
  <el-dialog :model-value="visible" title="收银台" width="420" :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)">
    <template v-if="pay">
      <p class="text-sm text-stone-500">订单号:<code class="font-mono text-xs">{{ orderNo }}</code></p>
      <template v-if="allowSandbox && pay.mode === 'sandbox'">
        <el-alert type="info" :closable="false" show-icon class="mt-4"
          title="沙箱模式" description="当前为沙箱支付,点击下方按钮即模拟支付成功并到账。" />
        <el-button type="primary" class="mt-5 w-full" size="large" :loading="paying" @click="confirmSandbox">
          模拟支付成功
        </el-button>
      </template>
      <template v-else>
        <!-- 微信 Native:二维码 -->
        <div v-if="method === 'wechat'" class="mt-4 flex flex-col items-center">
          <canvas ref="qrCanvas" class="rounded-lg border border-black/5 bg-white p-2"></canvas>
          <p class="mt-2 text-xs text-stone-400">请使用微信扫一扫完成支付</p>
        </div>
        <!-- 支付宝:跳转链接 -->
        <template v-else>
          <el-button type="primary" class="mt-4 w-full" size="large" @click="openPayPage">打开支付页面</el-button>
          <p class="mt-3 text-center text-xs text-stone-400">支付完成后页面会自动确认到账</p>
        </template>
        <el-button class="mt-3 w-full" @click="checkPaid">我已完成支付,查询到账</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup>
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'
import { getPayStatus, sandboxConfirm } from '../api'
import { isHttpsPayUrl, startStatusPolling } from '../utils/payment'

const props = defineProps({
  visible: { type: Boolean, default: false },
  orderNo: { type: String, default: '' },
  pay: { type: Object, default: null },   // { mode, qr_content, pay_url }
  method: { type: String, default: 'alipay' },
})
const emit = defineEmits(['update:visible', 'paid'])

const allowSandbox = import.meta.env.DEV
const paying = ref(false)
const qrCanvas = ref(null)
let stopPolling = null

// 弹窗懒渲染 + 过渡期间 canvas 可能尚未挂载,轮询等待就绪后再绘制(消除一次性 nextTick 的竞态)
watch(() => [props.visible, props.pay, props.method], async ([visible]) => {
  if (!visible) return
  const content = props.pay?.qr_content
  if (props.method !== 'wechat' || !content) return
  await nextTick()
  for (let i = 0; i < 20 && !qrCanvas.value; i++) {
    await new Promise((r) => setTimeout(r, 100))
    await nextTick()
  }
  if (!qrCanvas.value) {
    ElMessage.error('支付二维码生成失败,请重新创建订单')
    return
  }
  try {
    await QRCode.toCanvas(qrCanvas.value, content, { width: 200, margin: 1 })
  } catch {
    ElMessage.error('支付二维码生成失败,请重新创建订单')
  }
})

function poll(orderNo) {
  stopPolling?.()
  if (!orderNo) return
  stopPolling = startStatusPolling(
    async () => (await getPayStatus(orderNo)).data?.status,
    {
      onSuccess: () => emit('paid'),
      onError: (error) => { if (error.response?.status === 401) stopPolling?.() },
    },
  )
}

async function checkPaid() {
  const res = await getPayStatus(props.orderNo)
  if (res.data?.status === 'paid') {
    stopPolling?.()
    emit('paid')
  } else {
    ElMessage.info('暂未查询到支付结果,请稍后再试')
  }
}

function openPayPage() {
  const url = props.pay?.pay_url
  if (!isHttpsPayUrl(url)) {
    ElMessage.error('支付地址无效,请联系客服')
    return
  }
  const opened = window.open(url, '_blank', 'noopener,noreferrer')
  if (opened) opened.opener = null
}

async function confirmSandbox() {
  if (!allowSandbox) return
  paying.value = true
  try {
    await sandboxConfirm(props.orderNo)
    stopPolling?.()
    emit('paid')
  } finally { paying.value = false }
}

defineExpose({ poll })

onUnmounted(() => { stopPolling?.() })
</script>
