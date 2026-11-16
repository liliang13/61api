<template>
  <footer class="bg-[#1e1e2e] py-12 text-stone-400">
    <div class="mx-auto grid max-w-6xl gap-10 px-4 md:grid-cols-4">
      <div>
        <div class="mb-3 flex items-center gap-2">
          <img src="/logo-white.png?v=3" alt="61API" class="h-8 w-8" />
          <span class="text-[17px] font-bold text-white">61API</span>
        </div>
        <p class="text-[13px] leading-6">{{ store.isPrivate ? '企业 AI 网关 · 私有化部署。统一接入、组织配额、用量归因与审计。' : '一个 API Key,聚合全部主流大模型。' }}<br />{{ store.isPrivate ? '数据留在内网,账号由管理员统一开通。' : 'OpenAI 接口兼容,按量计费,随时启停。' }}</p>
      </div>
      <div>
        <h4 class="mb-3 text-sm font-bold text-white">产品</h4>
        <ul class="space-y-2 text-[13px]">
          <li><router-link class="hover:text-white" to="/models">模型列表</router-link></li>
          <li><router-link class="hover:text-white" to="/console/keys">API 密钥</router-link></li>
        </ul>
      </div>
      <div>
        <h4 class="mb-3 text-sm font-bold text-white">资源</h4>
        <ul class="space-y-2 text-[13px]">
          <li><router-link class="hover:text-white" to="/docs">接入文档</router-link></li>
          <li><router-link class="hover:text-white" to="/docs#tools">工具配置</router-link></li>
          <li><router-link class="hover:text-white" to="/docs#billing">计费说明</router-link></li>
        </ul>
      </div>
      <div>
        <h4 class="mb-3 text-sm font-bold text-white">联系我们</h4>
        <ul class="space-y-2 text-[13px]">
          <li><a href="mailto:contact@xiaoningkeji.com" class="hover:text-white">contact@xiaoningkeji.com</a></li>
          <li v-if="!store.isPrivate"><router-link class="hover:text-white" to="/terms">服务条款</router-link></li>
          <li v-if="!store.isPrivate"><router-link class="hover:text-white" to="/recharge-agreement">充值协议</router-link></li>
          <li v-if="!store.isPrivate"><router-link class="hover:text-white" to="/privacy">隐私政策</router-link></li>
        </ul>
      </div>
    </div>
    <div v-if="!store.isPrivate" class="mx-auto mt-10 max-w-6xl border-t border-white/10 px-4 pt-6 text-center text-xs leading-6 text-stone-500">
      <p>© {{ year }} 61API · 河北小柠科技有限公司 · <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener" class="hover:text-stone-300">冀ICP备2026009582号-7</a></p>
      <p class="mt-1 flex items-center justify-center gap-1">
        <img src="/beian.png" alt="公安备案" class="h-3.5 w-3.5" />
        <a href="https://beian.mps.gov.cn/#/query/webSearch?code=13040202001147" target="_blank" rel="noopener" class="hover:text-stone-300">冀公网安备13040202001147号</a>
      </p>
    </div>
    <div v-else class="mx-auto mt-10 max-w-6xl border-t border-white/10 px-4 pt-6 text-center text-xs leading-6 text-stone-500">
      <p>© {{ year }} 61API 私有化部署 · 内网使用</p>
    </div>
  </footer>
</template>

<script setup>
import { useUserStore } from '../stores/user'

const store = useUserStore()
const year = new Date().getFullYear()
</script>
