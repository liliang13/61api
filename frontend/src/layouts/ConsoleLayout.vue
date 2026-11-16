<template>
  <div class="min-h-screen bg-[#fafafa]">
    <!-- 站内公告 -->
    <div v-if="banner.visible"
      class="fixed inset-x-0 top-0 z-[60] flex h-10 items-center justify-center gap-2 bg-[#4f46e5] px-14 text-[13px] text-white shadow-sm">
      <span class="truncate">{{ banner.text }}</span>
      <a v-if="banner.link" :href="banner.link" target="_blank" rel="noopener"
        class="shrink-0 font-semibold underline underline-offset-2 transition-opacity hover:opacity-80">查看详情</a>
      <button aria-label="关闭公告" @click="dismissBanner"
        class="absolute right-4 flex h-6 w-6 items-center justify-center rounded transition-colors hover:bg-white/20">
        <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>

    <!-- 顶栏 -->
    <header :class="banner.visible ? 'top-10' : 'top-0'"
      class="fixed inset-x-0 z-50 flex h-[64px] items-center justify-between border-b border-black/5 bg-white/95 px-5 backdrop-blur">
      <router-link to="/" class="flex items-center gap-2">
        <img src="/logo-dark.png?v=3" alt="61API" class="h-8 w-8" />
        <span class="text-[17px] font-bold tracking-tight text-stone-800">61API</span>
        <el-tag size="small" effect="plain" class="ml-2">{{ store.isPrivate ? '私有化版' : '控制台' }}</el-tag>
      </router-link>
      <div class="flex items-center gap-1">
        <router-link v-for="item in siteNav" :key="item.to" :to="item.to"
          class="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm font-semibold text-stone-600 transition-colors hover:text-[#4f46e5]"
          active-class="!text-[#4f46e5]">
          <el-icon class="text-base"><component :is="item.icon" /></el-icon>{{ item.label }}
        </router-link>
      </div>
      <div class="flex items-center gap-4">
        <NoticeBell />
        <el-dropdown trigger="click" @command="onCommand">
          <span class="flex cursor-pointer items-center gap-2">
            <span class="grid h-8 w-8 place-items-center rounded-full bg-[#eef2ff] text-sm font-bold text-[#4f46e5]">
              {{ (store.info?.username || 'U').slice(0, 1).toUpperCase() }}
            </span>
            <span class="text-sm text-stone-700">{{ store.info?.username }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">账户设置</el-dropdown-item>
              <el-dropdown-item v-if="store.isAdmin" command="admin">管理后台</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div :class="banner.visible ? 'pt-[104px]' : 'pt-[64px]'" class="flex">
      <!-- 侧栏 -->
      <aside :class="banner.visible ? 'top-[104px]' : 'top-[64px]'"
        class="fixed bottom-0 left-0 flex w-[210px] flex-col overflow-y-auto border-r border-black/5 bg-white p-3">
        <div class="mb-3 rounded-xl bg-[#eef2ff] p-4">
          <p class="text-xs text-stone-500">{{ store.isPrivate ? '我的可用额度' : '当前余额' }}</p>
          <p class="mt-1 text-xl font-bold text-[#4f46e5]">¥{{ (store.info ? store.info.quota / 500000 : 0).toFixed(6) }}</p>
          <router-link v-if="store.feature('payments')" to="/console/topup">
            <el-button type="primary" size="small" class="mt-2 w-full">充值</el-button>
          </router-link>
        </div>
        <template v-for="item in menu" :key="item.to || 'sep-' + item.label">
          <div v-if="item.divider" class="my-2 border-t border-black/5"></div>
          <router-link v-else :to="item.to"
            class="mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-stone-600 hover:bg-[#f5f5f5]"
            active-class="!bg-[#eef2ff] !text-[#4f46e5]">
            <el-icon class="text-base"><component :is="item.icon" /></el-icon>{{ item.label }}
          </router-link>
        </template>
        <button @click="kefu.visible = true"
          class="mt-auto flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium text-stone-600 transition-colors hover:bg-[#f5f5f5] hover:text-[#4f46e5]">
          <el-icon class="text-base"><component :is="Headset" /></el-icon>联系客服
        </button>
      </aside>

      <!-- 主区 -->
      <main class="ml-[210px] min-w-0 flex-1 p-6">
        <router-view />
      </main>
    </div>

    <!-- 联系客服 -->
    <el-dialog v-model="kefu.visible" title="联系客服" width="360" align-center>
      <div class="flex flex-col items-center py-2">
        <img v-if="kefu.qr" :src="kefu.qr" alt="企业微信客服二维码"
          class="w-56 rounded-xl border border-black/5" />
        <div v-else class="grid h-56 w-56 place-items-center rounded-xl bg-[#f5f5f5] text-xs text-stone-400">
          客服二维码配置中
        </div>
        <p class="mt-4 text-center text-sm text-stone-600">
          {{ kefu.qr ? '微信扫一扫,添加企业微信客服' : '在线客服配置中,请先邮件联系' }}
        </p>
        <p class="mt-1 text-xs text-stone-400">{{ contactEmail }}</p>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import NoticeBell from '../components/NoticeBell.vue'
import { useUserStore } from '../stores/user'
import { getAnnouncement } from '../api'

const store = useUserStore()
const router = useRouter()

const contactEmail = 'contact@xiaoningkeji.com'
const kefu = ref({ visible: false, qr: computed(() => store.site?.kefu_qr_url || '') })

const DISMISS_KEY = '61api_announcement_read'
const banner = ref({ visible: false, text: '', link: '', version: '' })

import { BookOpen, Boxes, CreditCard, FileText, Gift, Headset, Home, KeyRound, LayoutDashboard, LifeBuoy, PackageOpen, ScrollText, Settings, Ticket } from 'lucide-vue-next'
const menu = computed(() => [
  // ── 核心使用 ──
  { to: '/console/dashboard', label: '数据看板', icon: LayoutDashboard },
  { to: '/console/keys', label: 'API 密钥', icon: KeyRound },
  { to: '/console/usage', label: '用量日志', icon: ScrollText },
  { divider: true, label: '财务' },
  // ── 财务 ──
  ...(store.feature('payments') ? [{ to: '/console/topup', label: '充值', icon: CreditCard }] : []),
  { to: '/console/resource-packs', label: '资源包', icon: PackageOpen },
  ...(store.feature('redeem') ? [{ to: '/console/redeem', label: '兑换码', icon: Ticket }] : []),
  ...(store.feature('invite') ? [{ to: '/console/invite', label: '邀请返佣', icon: Gift }] : []),
  ...(store.feature('invoice') ? [{ to: '/console/invoice', label: '发票管理', icon: FileText }] : []),
  { divider: true, label: '服务' },
  // ── 服务与账户 ──
  { to: '/console/tickets', label: '工单支持', icon: LifeBuoy },
  { to: '/console/profile', label: '账户设置', icon: Settings },
])

const siteNav = computed(() => [
  ...(store.isPrivate ? [] : [{ to: '/', label: '首页', icon: Home }]),
  { to: '/models', label: '模型列表', icon: Boxes },
  { to: '/docs', label: '文档中心', icon: BookOpen },
])

onMounted(() => {
  if (!store.info) store.fetchMe()
  loadBanner()
})

async function loadBanner() {
  try {
    const a = (await getAnnouncement()).data
    banner.value = {
      visible: !!(a.enabled && a.text && localStorage.getItem(DISMISS_KEY) !== a.updated_at),
      text: a.text, link: a.link, version: a.updated_at,
    }
  } catch { /* 公告加载失败不影响控制台使用 */ }
}

function dismissBanner() {
  banner.value.visible = false
  if (banner.value.version) localStorage.setItem(DISMISS_KEY, banner.value.version)
}

async function onCommand(cmd) {
  if (cmd === 'logout') {
    await store.logout()
    ElMessage.success('已退出登录')
    router.push('/')
  } else if (cmd === 'admin') {
    router.push('/admin/dashboard')
  } else if (cmd === 'profile') {
    router.push('/console/profile')
  }
}
</script>
