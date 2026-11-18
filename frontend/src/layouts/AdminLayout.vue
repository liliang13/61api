<template>
  <div class="min-h-screen bg-[#fafafa]">
    <header class="fixed inset-x-0 top-0 z-50 flex h-[60px] items-center justify-between border-b border-black/5 bg-white px-5">
      <div class="flex items-center gap-3">
        <router-link to="/" class="flex items-center gap-2">
          <img src="/logo-dark.png?v=3" alt="61API" class="h-8 w-8" />
          <span class="font-bold text-stone-800">61API <span class="text-[#4f46e5]">管理后台</span></span>
          <el-tag v-if="store.isPrivate" size="small" effect="plain">私有化</el-tag>
        </router-link>
      </div>
      <div class="flex items-center gap-4">
        <router-link to="/console/dashboard" class="text-sm text-stone-500 hover:text-[#4f46e5]">返回控制台</router-link>
        <el-button link type="danger" @click="logout">退出</el-button>
      </div>
    </header>

    <div class="flex pt-[60px]">
      <aside class="fixed bottom-0 left-0 top-[60px] w-[190px] overflow-y-auto border-r border-black/5 bg-white p-3">
        <div v-for="group in groups" :key="group.label" class="mb-1">
          <button
            class="flex w-full items-center justify-between rounded-md px-3 py-2 text-[14px] font-semibold text-stone-600 transition-colors hover:text-stone-800"
            @click="toggleGroup(group.label)">
            {{ group.label }}
            <svg viewBox="0 0 24 24" class="h-3.5 w-3.5 transition-transform"
              :class="collapsed.includes(group.label) ? '' : 'rotate-180'" fill="none"
              stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </button>
          <template v-if="!collapsed.includes(group.label)">
            <router-link v-for="item in group.items" :key="item.to" :to="item.to"
              class="mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 pl-[34px] text-[13px] font-medium text-stone-500 hover:bg-[#f5f5f5]"
              active-class="!bg-[#eef2ff] !text-[#4f46e5]">
              <el-icon class="text-[16px]"><component :is="item.icon" /></el-icon>{{ item.label }}
            </router-link>
          </template>
        </div>
      </aside>
      <main class="ml-[190px] min-w-0 flex-1 p-6">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const store = useUserStore()
const router = useRouter()

import { Building2, FileCheck, Gauge, Handshake, LifeBuoy, Megaphone, Network, PackageOpen, ReceiptText, ScrollText, Settings, ShieldCheck, Tags, Ticket, Users } from 'lucide-vue-next'
const collapsed = ref(JSON.parse(localStorage.getItem('admin_nav_collapsed') || '[]'))

function toggleGroup(label) {
  const i = collapsed.value.indexOf(label)
  if (i >= 0) collapsed.value.splice(i, 1)
  else collapsed.value.push(label)
  localStorage.setItem('admin_nav_collapsed', JSON.stringify(collapsed.value))
}

const groups = computed(() => [
  { label: '总览', items: [
    { to: '/admin/dashboard', label: '运营概览', icon: Gauge },
  ] },
  { label: '用户与工单', items: [
    { to: '/admin/users', label: '用户管理', icon: Users },
    { to: '/admin/tenants', label: '组织管理', icon: Building2 },
    { to: '/admin/tickets', label: '工单支持', icon: LifeBuoy },
    { to: '/admin/notices', label: '消息管理', icon: Megaphone },
  ] },
  { label: '模型与渠道', items: [
    { to: '/admin/channels', label: '渠道管理', icon: Network },
    { to: '/admin/models', label: '模型定价', icon: Tags },
  ] },
  { label: '财务', items: [
    { to: '/admin/resource-packs', label: '资源包', icon: PackageOpen },
    ...(store.feature('payments') ? [{ to: '/admin/orders', label: '充值订单', icon: ReceiptText }] : []),
    ...(store.feature('invoice') ? [{ to: '/admin/invoices', label: '发票管理', icon: FileCheck }] : []),
    ...(store.feature('redeem') ? [{ to: '/admin/codes', label: '兑换码', icon: Ticket }] : []),
    ...(store.feature('invite') ? [{ to: '/admin/invites', label: '邀请审计', icon: Handshake }] : []),
  ] },
  { label: '数据与审计', items: [
    { to: '/admin/logs', label: '全局用量', icon: ScrollText },
    { to: '/admin/audit', label: '审计日志', icon: ShieldCheck },
  ] },
  { label: '系统', items: [
    { to: '/admin/settings', label: '站点设置', icon: Settings },
  ] },
])

async function logout() {
  await store.logout()
  ElMessage.success('已退出登录')
  router.push('/')
}
</script>
