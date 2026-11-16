<template>
  <router-view />
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
let timer = null
let lastCheck = 0

// 发版后让旧标签页自动升级:对比 /version.json(构建时生成),
// 版本变化则整页刷新一次。
async function checkNewVersion() {
  const now = Date.now()
  if (now - lastCheck < 30000) return  // 节流
  lastCheck = now
  try {
    const r = await fetch('/version.json?t=' + now, { cache: 'no-store' })
    if (!r.ok) return
    const v = (await r.json()).v
    const known = localStorage.getItem('app_version')
    if (!known) {
      localStorage.setItem('app_version', String(v))
      return
    }
    if (String(v) !== known) {
      localStorage.setItem('app_version', String(v))
      location.reload()
    }
  } catch { /* 网络异常忽略 */ }
}

function scheduleCheck() {
  checkNewVersion()
}

onMounted(() => {
  scheduleCheck()
  timer = setInterval(checkNewVersion, 60000)
  router.afterEach(() => scheduleCheck())
})

onUnmounted(() => { clearInterval(timer) })
</script>
