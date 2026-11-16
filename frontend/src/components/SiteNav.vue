<template>
  <header class="fixed inset-x-0 top-0 z-50 h-[64px] border-b border-black/5 bg-white/95 backdrop-blur">
    <div class="mx-auto flex h-full max-w-6xl items-center justify-between px-4">
      <router-link to="/" class="flex items-center gap-2">
        <img src="/logo-dark.png?v=3" alt="61API" class="h-8 w-8" />
        <span class="text-[17px] font-bold tracking-tight text-stone-800">
          61API
        </span>
        <el-tag v-if="store.isPrivate" size="small" effect="plain">私有化版</el-tag>
      </router-link>

      <nav class="hidden items-center gap-1 md:flex">
        <router-link v-for="item in navItems" :key="item.to" :to="item.to"
          class="rounded-md px-3 py-2 text-sm font-semibold text-stone-600 transition-colors hover:text-[#4f46e5]"
          active-class="text-[#4f46e5]">
          {{ item.label }}
        </router-link>
      </nav>

      <div class="flex items-center gap-2">
        <template v-if="store.isLogin && store.info">
          <el-dropdown trigger="click" @command="onCommand">
            <span class="flex cursor-pointer items-center gap-2 rounded-full border border-black/10 px-3 py-1.5 text-sm text-stone-700">
              <span class="grid h-6 w-6 place-items-center rounded-full bg-[#eef2ff] text-xs font-bold text-[#4f46e5]">
                {{ (store.info.username || 'U').slice(0, 1).toUpperCase() }}
              </span>
              {{ store.info.username }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="console">控制台</el-dropdown-item>
                <el-dropdown-item v-if="store.isAdmin" command="admin">管理后台</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
        <template v-else>
          <router-link to="/login"
            class="rounded-lg px-4 py-2 text-sm font-semibold text-stone-700 hover:text-[#4f46e5]">登录</router-link>
          <router-link v-if="!store.isPrivate" to="/login?mode=register"
            class="rounded-lg brand-gradient px-4 py-2 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(79,70,229,0.3)] hover:opacity-90">
            免费注册
          </router-link>
        </template>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const store = useUserStore()
const router = useRouter()

const navItems = computed(() => [
  ...(store.isPrivate ? [] : [{ to: '/', label: '首页' }]),
  { to: '/models', label: '模型列表' },
  { to: '/docs', label: '文档中心' },
])

async function onCommand(cmd) {
  if (cmd === 'logout') {
    await store.logout()
    ElMessage.success('已退出登录')
    router.push('/')
  } else if (cmd === 'console') {
    router.push('/console/dashboard')
  } else if (cmd === 'admin') {
    router.push('/admin/dashboard')
  }
}
</script>
