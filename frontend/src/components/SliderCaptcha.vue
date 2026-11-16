<template>
  <div v-if="visible" class="fixed inset-0 z-[100] grid place-items-center bg-black/50 px-4" @click.self="cancel">
    <div class="w-full max-w-[340px] rounded-2xl bg-white p-4 shadow-2xl">
      <div class="mb-3 flex items-center justify-between">
        <span class="text-sm font-semibold text-stone-700">安全验证</span>
        <el-button link @click="cancel">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>

      <!-- 拼图区 -->
      <div class="relative select-none overflow-hidden rounded-lg bg-[#f0f0f0]" :style="{ height: bh + 'px' }">
        <img v-if="bgUrl" :src="bgUrl" class="block w-full" :style="{ height: bh + 'px' }" draggable="false" />
        <img v-if="pieceUrl" :src="pieceUrl" class="absolute" draggable="false"
          :style="{ height: ph + 'px', top: topY + 'px', left: dx + 'px' }" />
        <div v-if="loading" class="absolute inset-0 grid place-items-center text-xs text-stone-400">加载中…</div>
      </div>

      <!-- 滑轨 -->
      <div ref="track" class="relative mt-3 h-10 select-none rounded-lg bg-[#f5f5f5]">
        <div class="absolute inset-y-0 left-0 rounded-lg bg-[#eef2ff]/70" :style="{ width: dx + HANDLE + 'px' }"></div>
        <span class="pointer-events-none absolute inset-0 grid place-items-center text-xs text-stone-400"
          :style="{ opacity: dx > 8 ? 0 : 1 }">按住滑块,拖动完成拼图</span>
        <div ref="handle" class="absolute top-0 grid h-10 w-10 cursor-grab place-items-center rounded-lg bg-white shadow-md active:cursor-grabbing"
          :style="{ left: dx + 'px' }"
          @mousedown.prevent="startDrag" @touchstart.prevent="startDrag">
          <el-icon class="text-stone-500"><Right /></el-icon>
        </div>
      </div>

      <p v-if="tip" class="mt-2 text-center text-xs" :class="tipOk ? 'text-green-600' : 'text-red-500'">{{ tip }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Close, Right } from '@element-plus/icons-vue'
import http from '../api/http'

const HANDLE = 40
const visible = ref(false)
const loading = ref(false)
const bgUrl = ref('')
const pieceUrl = ref('')
const topY = ref(0)
const ph = ref(60)
const bh = ref(160)
const dx = ref(0)
const tip = ref('')
const tipOk = ref(false)
const track = ref(null)
const handle = ref(null)

let cid = ''
let maxDx = 280
let resolvePass = null
let rejectPass = null

function startDrag(e) {
  const startX = e.touches ? e.touches[0].clientX : e.clientX
  const startDx = dx.value
  const move = (ev) => {
    const cur = ev.touches ? ev.touches[0].clientX : ev.clientX
    dx.value = Math.max(0, Math.min(maxDx, Math.round(startDx + cur - startX)))
  }
  const up = async () => {
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', up)
    document.removeEventListener('touchmove', move)
    document.removeEventListener('touchend', up)
    await verify()
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', up)
  document.addEventListener('touchmove', move)
  document.addEventListener('touchend', up)
}

async function load() {
  loading.value = true
  tip.value = ''
  try {
    const res = await http.get('/captcha/new')
    const d = res.data
    cid = d.cid
    bgUrl.value = d.bg
    pieceUrl.value = d.piece
    topY.value = d.top
    ph.value = d.ph
    bh.value = d.bh
    maxDx = d.bw - HANDLE
  } catch { tip.value = '加载失败,请重试'; tipOk.value = false }
  finally { loading.value = false }
}

async function verify() {
  if (dx.value < 8) return
  tip.value = '校验中…'
  tipOk.value = false
  try {
    const res = await http.post('/captcha/check', { cid, x: dx.value, phone: currentPhone.value })
    const ticket = res.data.ticket
    tip.value = '验证通过'
    tipOk.value = true
    setTimeout(() => { visible.value = false; resolvePass(ticket) }, 250)
  } catch (e) {
    const msg = e.response?.data?.message || '验证失败,请重试'
    const refresh = e.response?.data?.refresh
    tip.value = msg
    tipOk.value = false
    dx.value = 0
    if (refresh) await load()
  }
}

const currentPhone = ref('')

/** 对外 API:弹出滑块,验证通过 resolve(ticket);取消 reject。 */
function open(phone) {
  currentPhone.value = phone
  dx.value = 0
  tip.value = ''
  visible.value = true
  load()
  return new Promise((resolve, reject) => {
    resolvePass = resolve
    rejectPass = reject
  })
}

function cancel() {
  visible.value = false
  if (rejectPass) rejectPass(new Error('cancelled'))
}

defineExpose({ open })
</script>
