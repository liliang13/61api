<template>
  <div class="max-w-lg">
    <h1 class="text-xl font-bold text-stone-800">兑换码</h1>
    <p class="mt-2 text-xs text-stone-400">输入兑换码立即到账,每个兑换码只能使用一次。</p>
    <div class="mt-6 flex gap-3">
      <el-input v-model="code" placeholder="例如 61-1A2B3C4D" size="large" class="!max-w-xs" @keydown.enter="doRedeem" />
      <el-button type="primary" size="large" :loading="loading" @click="doRedeem">兑换</el-button>
    </div>
    <div v-if="result" class="mt-5 rounded-xl border border-[#4f46e5]/20 bg-[#eef2ff] p-4">
      <p class="text-sm font-semibold text-[#4f46e5]">兑换成功!</p>
      <p class="mt-1 text-sm text-stone-600">到账 ¥{{ result.yuan.toFixed(2) }},当前余额 ¥{{ (result.balance / 500000).toFixed(6) }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { redeem } from '../../api'
import { useUserStore } from '../../stores/user'

const store = useUserStore()
const code = ref('')
const loading = ref(false)
const result = ref(null)

async function doRedeem() {
  if (!code.value.trim()) return
  loading.value = true
  try {
    result.value = (await redeem(code.value.trim().toUpperCase())).data
    code.value = ''
    await store.fetchMe()
  } finally { loading.value = false }
}
</script>
