import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const routes = [
  { path: '/', name: 'home', component: () => import('../views/Home.vue') },
  { path: '/models', name: 'models', component: () => import('../views/ModelsView.vue') },
  { path: '/docs', name: 'docs', component: () => import('../views/DocsView.vue') },
  { path: '/terms', name: 'terms', component: () => import('../views/TermsView.vue') },
  { path: '/recharge-agreement', name: 'recharge-agreement', component: () => import('../views/RechargeAgreementView.vue') },
  { path: '/privacy', name: 'privacy', component: () => import('../views/PrivacyView.vue') },
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  {
    path: '/console',
    component: () => import('../layouts/ConsoleLayout.vue'),
    meta: { auth: true },
    children: [
      { path: '', redirect: '/console/dashboard' },
      { path: 'dashboard', name: 'console-dashboard', component: () => import('../views/console/Dashboard.vue') },
      { path: 'keys', name: 'console-keys', component: () => import('../views/console/Keys.vue') },
      { path: 'usage', name: 'console-usage', component: () => import('../views/console/Usage.vue') },
      { path: 'topup', name: 'console-topup', component: () => import('../views/console/Topup.vue'), meta: { feature: 'payments' } },
      { path: 'resource-packs', name: 'console-resource-packs', component: () => import('../views/console/ResourcePacks.vue') },
      { path: 'redeem', name: 'console-redeem', component: () => import('../views/console/Redeem.vue'), meta: { feature: 'redeem' } },
      { path: 'invite', name: 'console-invite', component: () => import('../views/console/Invite.vue'), meta: { feature: 'invite' } },
      { path: 'invoice', name: 'console-invoice', component: () => import('../views/console/FInvoice.vue'), meta: { feature: 'invoice' } },
      { path: 'tickets', name: 'console-tickets', component: () => import('../views/console/Tickets.vue') },
      { path: 'tickets/:id', name: 'console-ticket-detail', component: () => import('../views/console/TicketDetail.vue') },
      { path: 'notices', name: 'console-notices', component: () => import('../views/console/Notices.vue') },
      { path: 'notices/:id', name: 'console-notice-detail', component: () => import('../views/console/NoticeDetail.vue') },
      { path: 'profile', name: 'console-profile', component: () => import('../views/console/Profile.vue') },
    ],
  },
  {
    path: '/admin',
    component: () => import('../layouts/AdminLayout.vue'),
    meta: { auth: true, admin: true },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'admin-dashboard', component: () => import('../views/admin/ADashboard.vue') },
      { path: 'users', name: 'admin-users', component: () => import('../views/admin/AUsers.vue') },
      { path: 'tenants', name: 'admin-tenants', component: () => import('../views/admin/ATenants.vue') },
      { path: 'channels', name: 'admin-channels', component: () => import('../views/admin/AChannels.vue') },
      { path: 'models', name: 'admin-models', component: () => import('../views/admin/AModels.vue') },
      { path: 'orders', name: 'admin-orders', component: () => import('../views/admin/AOrders.vue'), meta: { feature: 'payments' } },
      { path: 'resource-packs', name: 'admin-resource-packs', component: () => import('../views/admin/AResourcePacks.vue') },
      { path: 'codes', name: 'admin-codes', component: () => import('../views/admin/ACodes.vue'), meta: { feature: 'redeem' } },
      { path: 'invites', name: 'admin-invites', component: () => import('../views/admin/AInvites.vue'), meta: { feature: 'invite' } },
      { path: 'invoices', name: 'admin-invoices', component: () => import('../views/admin/AInvoices.vue'), meta: { feature: 'invoice' } },
      { path: 'audit', name: 'admin-audit', component: () => import('../views/admin/AAudit.vue') },
      { path: 'logs', name: 'admin-logs', component: () => import('../views/admin/ALogs.vue') },
      { path: 'tickets', name: 'admin-tickets', component: () => import('../views/admin/ATickets.vue') },
      { path: 'tickets/:id', name: 'admin-ticket-detail', component: () => import('../views/admin/ATicketDetail.vue') },
      { path: 'notices', name: 'admin-notices', component: () => import('../views/admin/ANotices.vue') },
      { path: 'settings', name: 'admin-settings', component: () => import('../views/admin/ASettings.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

// 发布后旧标签页内存里引用的懒加载 chunk 可能已被服务器删除,导入失败时
// 自动整页刷新一次拿到新版入口(sessionStorage 防循环刷新)
router.onError((error, to) => {
  const msg = String(error?.message || '')
  if (msg.includes('Failed to fetch dynamically imported module')
    || msg.includes('error loading dynamically imported module')
    || msg.includes('Importing a module script failed')) {
    if (!sessionStorage.getItem('61api_chunk_reload')) {
      sessionStorage.setItem('61api_chunk_reload', String(Date.now()))
      window.location.assign(to?.fullPath || '/')
    }
  }
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  await store.ensureSite()
  if (!store.restored) {
    try {
      await store.restoreSession()
    } catch {
      if (to.meta.auth) {
        ElMessage.error('暂时无法验证登录状态,请检查网络后重试')
        return false
      }
    }
  }
  // 私有化部署没有对外官网,入口直接是登录页/控制台
  if (store.isPrivate && to.path === '/') {
    return store.isLogin ? '/console/dashboard' : '/login'
  }
  if (to.meta.feature && !store.feature(to.meta.feature)) {
    ElMessage.warning('该功能在当前部署中未启用')
    return store.isLogin ? '/console/dashboard' : '/login'
  }
  if (to.meta.auth && !store.isLogin) {
    ElMessage.warning('请先登录')
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && store.info?.role !== 'admin') {
    ElMessage.error('需要管理员权限')
    return '/'
  }
  return true
})

export default router
