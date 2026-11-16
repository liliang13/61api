<template>
  <div class="min-h-screen bg-white pt-[64px]">
    <SiteNav />

    <!-- Hero -->
    <section class="hero-bg border-b border-black/5">
      <div class="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 md:grid-cols-2 md:py-24">
        <div>
          <span class="inline-flex items-center gap-2 rounded-full border border-[#4f46e5]/20 bg-white px-3 py-1 text-xs font-semibold text-[#4f46e5]">
            <span class="h-1.5 w-1.5 rounded-full bg-[#4f46e5]"></span>
            OpenAI 接口兼容 · 一个 Key 通达全部模型
          </span>
          <h1 class="mt-6 text-4xl font-bold leading-tight tracking-tight text-stone-800 md:text-[52px]">
            一个 <span class="brand-text-gradient">API Key</span>,<br />聚合所有主流大模型
          </h1>
          <p class="mt-5 max-w-lg text-[15px] leading-7 text-stone-500">
            DeepSeek、GLM、Kimi、MiniMax 等国产主流大模型,统一入口、统一计费。
            改一行 Base URL 和密钥即可迁移,主流模型长期低价,注册即送体验金。
          </p>
          <div class="mt-8 flex flex-wrap items-center gap-3">
            <router-link to="/login?mode=register"
              class="rounded-xl brand-gradient px-8 py-3 text-[15px] font-semibold text-white shadow-[0_4px_16px_rgba(79,70,229,0.35)] hover:opacity-90">
              免费开始使用
            </router-link>
            <router-link to="/docs"
              class="rounded-xl border-2 border-[#4f46e5] px-8 py-3 text-[15px] font-semibold text-[#4f46e5] hover:bg-[#4f46e5]/5">
              查看接入文档
            </router-link>
          </div>
          <div class="mt-10 flex gap-10">
            <div v-for="s in heroStats" :key="s.label">
              <div class="text-2xl font-bold text-[#4f46e5] md:text-3xl">{{ s.num }}</div>
              <div class="mt-1 text-xs text-stone-400">{{ s.label }}</div>
            </div>
          </div>
        </div>

        <div class="code-window overflow-hidden">
          <div class="flex items-center gap-2 border-b border-white/10 px-4 py-3">
            <span class="dot bg-[#ff5f57]"></span><span class="dot bg-[#febc2e]"></span><span class="dot bg-[#28c840]"></span>
            <span class="ml-3 text-xs text-stone-400">quick_start.py</span>
            <span class="ml-auto rounded bg-[#28c840]/15 px-2 py-0.5 text-[10px] font-bold text-[#28c840]">Python</span>
          </div>
          <pre class="codeblock"><span class="text-stone-500"># 1. pip install openai   2. 替换 base_url 与 api_key 即完成迁移</span>
<span class="text-[#c586c0]">from</span> openai <span class="text-[#c586c0]">import</span> OpenAI

client = OpenAI(
    api_key=<span class="text-[#ce9178]">"sk-你的密钥"</span>,
    base_url=<span class="text-[#ce9178]">"{{ baseUrl }}"</span>,
)

resp = client.chat.completions.create(
    model=<span class="text-[#ce9178]">"deepseek-flash"</span>,
    messages=[{<span class="text-[#ce9178]">"role"</span>: <span class="text-[#ce9178]">"user"</span>,
               <span class="text-[#ce9178]">"content"</span>: <span class="text-[#ce9178]">"用一句话介绍你自己"</span>}],
)
<span class="text-[#dcdcaa]">print</span>(resp.choices[0].message.content)</pre>
        </div>
      </div>
    </section>

    <!-- 工具兼容 -->
    <section class="border-b border-black/5 bg-[#fafafa] py-8">
      <div class="mx-auto max-w-6xl px-4 text-center">
        <p class="text-xs font-semibold uppercase tracking-widest text-stone-400">开箱即用</p>
        <div class="mt-4 flex flex-wrap items-center justify-center gap-3">
          <span v-for="t in tools" :key="t"
            class="rounded-full border border-black/5 bg-white px-5 py-2 text-sm font-semibold text-stone-600 shadow-sm">
            {{ t }}
          </span>
        </div>
      </div>
    </section>

    <!-- 快速接入三步 -->
    <section class="py-20">
      <div class="mx-auto max-w-6xl px-4">
        <h2 class="text-center text-3xl font-bold text-stone-800">三步完成接入</h2>
        <p class="mt-3 text-center text-sm text-stone-500">全程不超过 5 分钟,改两行配置,业务代码零改动</p>
        <div class="mt-10 grid items-start gap-10 md:grid-cols-[1fr_1.2fr]">
          <div class="space-y-6">
            <div v-for="(step, i) in steps" :key="i" class="flex gap-4">
              <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#eef2ff] font-bold text-[#4f46e5]">{{ i + 1 }}</span>
              <div>
                <h3 class="font-bold text-stone-800">{{ step.title }}</h3>
                <p class="mt-1 text-sm leading-6 text-stone-500">{{ step.desc }}</p>
              </div>
            </div>
          </div>
          <div class="code-window overflow-hidden">
            <div class="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
              <span class="dot bg-[#ff5f57]"></span><span class="dot bg-[#febc2e]"></span><span class="dot bg-[#28c840]"></span>
              <div class="ml-4 flex gap-1">
                <button v-for="lang in Object.keys(codeSamples)" :key="lang" @click="activeLang = lang"
                  class="rounded-md px-3 py-1 text-xs font-semibold transition-colors"
                  :class="activeLang === lang ? 'bg-white/15 text-white' : 'text-stone-400 hover:text-white'">
                  {{ lang }}
                </button>
              </div>
            </div>
            <pre class="codeblock" v-html="codeSamples[activeLang]"></pre>
          </div>
        </div>
      </div>
    </section>

    <!-- 开放接口 -->
    <section class="border-y border-black/5 py-20">
      <div class="mx-auto max-w-6xl px-4">
        <h2 class="text-center text-3xl font-bold text-stone-800">开放接口</h2>
        <p class="mt-3 text-center text-sm text-stone-500">标准 REST API,任何支持 OpenAI 协议的 SDK 与工具均可直连</p>
        <div class="mt-10 grid items-start gap-10 md:grid-cols-2">
          <div>
            <div class="rounded-2xl bg-[#1e1e2e] p-5">
              <p class="text-xs text-stone-400">API Base URL</p>
              <div class="mt-2 flex items-center justify-between gap-3">
                <code class="truncate font-mono text-sm font-bold text-[#a5d6ff]">{{ baseUrl }}</code>
                <button @click="copyBase"
                  class="shrink-0 rounded-md bg-white/10 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-white/20">
                  复制
                </button>
              </div>
            </div>
            <div class="mt-4 overflow-hidden rounded-2xl border border-black/5">
              <table class="w-full text-sm">
                <tbody class="divide-y divide-black/5 bg-white">
                  <tr v-for="e in endpoints" :key="e.path" class="hover:bg-[#fafaff]">
                    <td class="w-[78px] px-4 py-3.5">
                      <span class="rounded px-2 py-0.5 font-mono text-[11px] font-bold text-white"
                        :class="e.method === 'GET' ? 'bg-[#16a34a]' : 'bg-[#4f46e5]'">{{ e.method }}</span>
                    </td>
                    <td class="px-2 py-3.5 font-mono text-xs text-stone-700">{{ e.path }}</td>
                    <td class="px-4 py-3.5 text-right text-xs text-stone-400">{{ e.desc }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p class="mt-3 text-xs leading-6 text-stone-400">
              鉴权:请求头 <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono">Authorization: Bearer sk-...</code>
              · 完整参数与错误码见<a href="/docs" class="font-semibold text-[#4f46e5] hover:underline">文档中心</a>
            </p>
          </div>
          <div v-if="hasVectorModel" class="code-window overflow-hidden">
            <div class="flex items-center gap-2 border-b border-white/10 px-4 py-3">
              <span class="dot bg-[#ff5f57]"></span><span class="dot bg-[#febc2e]"></span><span class="dot bg-[#28c840]"></span>
              <span class="ml-3 text-xs text-stone-400">embeddings_demo.py</span>
              <span class="ml-auto rounded bg-[#28c840]/15 px-2 py-0.5 text-[10px] font-bold text-[#28c840]">Python</span>
            </div>
            <pre class="codeblock"><span class="text-stone-500"># 向量接口:文本转向量,适用检索 / RAG 场景</span>
<span class="text-[#c586c0]">from</span> openai <span class="text-[#c586c0]">import</span> OpenAI

client = OpenAI(
    api_key=<span class="text-[#ce9178]">"sk-你的密钥"</span>,
    base_url=<span class="text-[#ce9178]">"{{ baseUrl }}"</span>,
)

vec = client.embeddings.create(
    model=<span class="text-[#ce9178]">"text-embedding-3-small"</span>,
    input=[<span class="text-[#ce9178]">"一个 Key,聚合所有主流大模型"</span>],
)
<span class="text-[#dcdcaa]">print</span>(<span class="text-[#dcdcaa]">len</span>(vec.data[0].embedding), <span class="text-[#ce9178]">"维向量"</span>)</pre>
          </div>
        </div>
      </div>
    </section>

    <!-- 企业服务 -->
    <section class="border-y border-black/5 bg-[#fafafa] py-20">
      <div class="mx-auto max-w-6xl px-4">
        <div class="text-center">
          <span class="inline-flex items-center gap-2 rounded-full border border-[#4f46e5]/20 bg-white px-3 py-1 text-xs font-semibold text-[#4f46e5]">
            企业服务
          </span>
          <h2 class="mt-4 text-3xl font-bold text-stone-800">面向企业采购的 API 平台</h2>
          <p class="mt-3 text-sm text-stone-500">从付款到用量的全流程合规,决策者与管理员都省心</p>
        </div>
        <div class="mt-12 grid gap-5 md:grid-cols-3">
          <div v-for="e in enterprise" :key="e.title"
            class="card-hover rounded-2xl border border-black/5 bg-white p-7">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-[#eef2ff] text-[#4f46e5]">
              <el-icon :size="22"><component :is="e.icon" /></el-icon>
            </span>
            <h3 class="mt-4 font-bold text-stone-800">{{ e.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-stone-500">{{ e.desc }}</p>
          </div>
        </div>
        <p class="mt-8 text-center text-sm text-stone-400">
          需要企业采购方案或 SLA 协议?联系我们:
          <a href="mailto:contact@xiaoningkeji.com" class="font-semibold text-[#4f46e5] hover:underline">contact@xiaoningkeji.com</a>
        </p>
      </div>
    </section>

    <!-- 为什么选我们 -->
    <section class="bg-white py-20">
      <div class="mx-auto max-w-6xl px-4">
        <h2 class="text-center text-3xl font-bold text-stone-800">为什么选择 61API</h2>
        <div class="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="f in features" :key="f.title"
            class="card-hover rounded-2xl border border-black/5 bg-white p-7">
            <span class="grid h-11 w-11 place-items-center rounded-xl bg-[#eef2ff] text-[#4f46e5]">
              <el-icon :size="22"><component :is="f.icon" /></el-icon>
            </span>
            <h3 class="mt-4 font-bold text-stone-800">{{ f.title }}</h3>
            <p class="mt-2 text-sm leading-6 text-stone-500">{{ f.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 价格速览 -->
    <section class="py-20">
      <div class="mx-auto max-w-6xl px-4">
        <div class="text-center">
          <h2 class="text-3xl font-bold text-stone-800">主流模型 <span class="brand-text-gradient">{{ discountLabel }} </span> 起</h2>
          <p class="mt-3 text-sm text-stone-500">按 Token 计量,无最低消费,余额长期有效 · 以下为部分热门模型单价(每百万 Tokens)</p>
        </div>
        <div class="mx-auto mt-10 max-w-3xl overflow-hidden rounded-2xl border border-black/5">
          <table class="w-full text-sm">
            <thead class="bg-[#eef2ff] text-left text-stone-600">
              <tr>
                <th class="px-5 py-3 font-semibold">模型</th>
                <th class="px-5 py-3 text-right font-semibold">输入 ¥/1M</th>
                <th class="px-5 py-3 text-right font-semibold">输出 ¥/1M</th>
                <th class="px-5 py-3 text-center font-semibold">折扣</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-black/5 bg-white">
              <tr v-for="m in pricePreview" :key="m.id" class="hover:bg-[#fafaff]">
                <td class="px-5 py-3 font-semibold text-stone-700">{{ m.display_name }}</td>
                <td class="px-5 py-3 text-right text-stone-600">¥{{ m.input_price.toFixed(2) }}</td>
                <td class="px-5 py-3 text-right text-stone-600">¥{{ m.output_price.toFixed(2) }}</td>
                <td class="px-5 py-3 text-center">
                  <span v-if="discountOf(m)" class="font-semibold text-[#4f46e5]">{{ discountOf(m) }}</span>
                  <span v-else class="text-stone-300">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-6 text-center">
          <router-link to="/models" class="text-sm font-semibold text-[#4f46e5] hover:underline">
            查看完整模型与价格列表 →
          </router-link>
        </div>
      </div>
    </section>

    <!-- FAQ -->
    <section class="bg-[#fafafa] py-20">
      <div class="mx-auto max-w-3xl px-4">
        <h2 class="text-center text-3xl font-bold text-stone-800">常见问题</h2>
        <div class="mt-10 overflow-hidden rounded-2xl border border-black/5 bg-white">
          <el-collapse class="faq-collapse">
            <el-collapse-item v-for="q in faqs" :key="q.q" :title="q.q" :name="q.q">
              <p class="text-sm leading-7 text-stone-500">{{ q.a }}</p>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="brand-gradient py-16">
      <div class="mx-auto max-w-4xl px-4 text-center text-white">
        <h2 class="text-3xl font-bold">现在注册,领取体验金</h2>
        <p class="mx-auto mt-4 max-w-xl text-[15px] leading-7 text-white/80">
          注册即送体验额度,无需绑定支付方式,创建密钥后立刻开始调用全部模型。
        </p>
        <router-link to="/login?mode=register"
          class="mt-8 inline-block rounded-xl bg-white px-10 py-3.5 text-[15px] font-bold text-[#4f46e5] shadow-lg hover:bg-white/90">
          免费注册
        </router-link>
      </div>
    </section>

    <SiteFooter />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Building2, ChartColumn, Layers, Plug, ReceiptText, ShieldCheck, Users, Wallet, Zap } from 'lucide-vue-next'
import SiteNav from '../components/SiteNav.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { getPublicModels, getSiteInfo } from '../api'
import { API_BASE_URL } from '../apiOrigin'
import { copyText } from '../utils/clipboard'

const baseUrl = API_BASE_URL

const hasVectorModel = ref(false)
const endpoints = computed(() => [
  { method: 'POST', path: '/v1/chat/completions', desc: '对话补全 · OpenAI 标准' },
  { method: 'POST', path: '/v1/messages', desc: 'Anthropic 标准 · Claude Code 直连' },
  { method: 'POST', path: '/v1/responses', desc: 'OpenAI Responses 标准' },
  // 目录里存在向量模型(embedding 名或"向量"标签)才展示向量能力,与在售目录自动保持一致
  ...(hasVectorModel.value
    ? [{ method: 'POST', path: '/v1/embeddings', desc: '文本向量化' }]
    : []),
  { method: 'GET', path: '/v1/models', desc: '模型列表' },
])

async function copyBase() {
  await copyText(baseUrl, 'Base URL 已复制')
}

const heroStats = ref([
  { num: '多款', label: '在售大模型 · 持续上新' },
  { num: '1:1', label: '人民币充值直兑额度' },
  { num: '7×24', label: '网关服务' },
])
const discountLabel = ref('5 折')

// 实际折扣 = 售价相对官方原价(取输入/输出中更低的折扣);原价未填(0)的模型不计入
function discountOf(m) {
  const rates = []
  if (m.official_input > 0) rates.push(m.input_price / m.official_input)
  if (m.official_output > 0) rates.push(m.output_price / m.official_output)
  if (!rates.length) return null
  return Math.round(Math.min(...rates) * 100) / 10 + ' 折'
}
const pricePreview = ref([])

const tools = ['Cursor', 'Cline', 'Dify', 'LobeChat', 'Continue', 'Cherry Studio', 'NextChat', 'Open WebUI']

const steps = [
  { title: '注册账号', desc: '手机号或用户名注册,自动获得体验金,无需绑卡。' },
  { title: '创建 API 密钥', desc: '在控制台一键生成 sk- 密钥,支持为每个密钥单独设额度。' },
  { title: '替换 Base URL', desc: '把接口地址改为本站 /v1,填入密钥,业务代码即刻跑通全部模型。' },
]

const codeSamples = {
  Python: `<span class="text-stone-500"># pip install openai</span>
<span class="text-[#c586c0]">from</span> openai <span class="text-[#c586c0]">import</span> OpenAI

client = OpenAI(
    api_key=<span class="text-[#ce9178]">"sk-..."</span>,
    base_url=<span class="text-[#ce9178]">"${baseUrl}"</span>,
)
resp = client.chat.completions.create(
    model=<span class="text-[#ce9178]">"deepseek-flash"</span>,
    messages=[{<span class="text-[#ce9178]">"role"</span>: <span class="text-[#ce9178]">"user"</span>, <span class="text-[#ce9178]">"content"</span>: <span class="text-[#ce9178]">"你好"</span>}],
)`,
  'Node.js': `<span class="text-stone-500">// npm install openai</span>
<span class="text-[#c586c0]">import</span> OpenAI <span class="text-[#c586c0]">from</span> <span class="text-[#ce9178]">"openai"</span>;

<span class="text-[#c586c0]">const</span> client = <span class="text-[#c586c0]">new</span> <span class="text-[#dcdcaa]">OpenAI</span>({
  apiKey: <span class="text-[#ce9178]">"sk-..."</span>,
  baseURL: <span class="text-[#ce9178]">"${baseUrl}"</span>,
});
<span class="text-[#c586c0]">const</span> resp = <span class="text-[#c586c0]">await</span> client.chat.completions.<span class="text-[#dcdcaa]">create</span>({
  model: <span class="text-[#ce9178]">"deepseek-flash"</span>,
  messages: [{ role: <span class="text-[#ce9178]">"user"</span>, content: <span class="text-[#ce9178]">"你好"</span> }],
});`,
  cURL: `curl ${baseUrl}/chat/completions \\
  -H <span class="text-[#ce9178]">"Content-Type: application/json"</span> \\
  -H <span class="text-[#ce9178]">"Authorization: Bearer sk-..."</span> \\
  -d <span class="text-[#ce9178]">'{
    "model": "deepseek-flash",
    "messages": [{"role": "user", "content": "你好"}]
  }'</span>`,
}
const activeLang = ref('Python')

const enterprise = [
  { icon: Building2, title: '对公采购', desc: '对公转账、合规发票、财务可入账。' },
  { icon: ShieldCheck, title: '安全合规', desc: '成员权限与访问审计,含 SLA 支持。' },
  { icon: ChartColumn, title: '成本透明', desc: '统一配额、用量看板,团队预算可控。' },
]

const features = [
  { icon: Layers, title: '多模型聚合', desc: '一家接入,全模型可用。新增模型自动上架,无需逐家申请账号与充值。' },
  { icon: Wallet, title: '价格透明', desc: '按 Token 计量,单价与用量全程可查,主流模型长期低价,支持明细导出。' },
  { icon: Zap, title: '稳定低延迟', desc: '多线路智能路由与故障自动切换,单点异常不中断服务。' },
  { icon: Plug, title: '标准兼容', desc: '完全兼容 OpenAI 接口格式,现有 SDK 与框架无需改造。' },
  { icon: ReceiptText, title: '企业友好', desc: '支持对公转账与增值税发票,采购流程合规,团队统一结算。' },
  { icon: Users, title: '团队协作', desc: '邀请成员共享额度,分密钥管理调用权限,消费一目了然。' },
]

const faqs = [
  { q: '如何获取 API Key?', a: '注册并登录后,进入控制台「API 密钥」页面,点击「新建密钥」即可生成 sk- 开头的密钥。密钥仅在创建时完整展示一次,请妥善保存。' },
  { q: '接口和 OpenAI 完全兼容吗?', a: '兼容。将 base_url 替换为本站地址、api_key 替换为本站密钥后,openai 官方 SDK、LangChain、各类客户端工具均可直接使用,包括流式输出。' },
  { q: '如何计费?余额会过期吗?', a: '按各模型单价与实际 Token 用量计费,调用结束实时扣费,控制台可查每笔明细。充值余额长期有效,无最低消费。' },
  { q: '调用报错怎么办?', a: '先检查密钥是否有效、余额是否充足;401 为密钥错误,402 为余额不足,502/503 为上游异常(通常自动重试即可)。更多说明见文档中心的错误码表。' },
]

onMounted(async () => {
  try {
    const [info, models] = await Promise.all([getSiteInfo(), getPublicModels()])
    const catalog = models.data || []
    // 首条统计始终跟随模型定价目录实况:后台上下架/新增模型,首页数字自动变化
    heroStats.value[0] = { num: `${catalog.length} 款`, label: '在售大模型 · 持续上新' }
    // 向量能力展示开关:目录里有 embedding 名或"向量"标签的模型才露出 embeddings 相关内容
    hasVectorModel.value = catalog.some(
      (m) => /embed/i.test(m.name || '') || (Array.isArray(m.tags) && m.tags.includes('向量')))
    const hs = info.data.hero_stats
    // 第 2/3 条仍可被站点设置覆盖;第 1 条不读 hero_stats,避免文案与目录脱节
    if (hs?.stat2) heroStats.value[1] = hs.stat2
    if (hs?.stat3) heroStats.value[2] = hs.stat3
    // 折扣文案:后台「首页折扣文案」优先;留空才按目录自动算最低实际折扣(相对官方原价)
    const note = Number(info.data.discount_note || 0)
    if (note > 0) {
      discountLabel.value = Math.round(note * 100) / 10 + ' 折'
    } else {
      const ds = catalog
        .map((m) => {
          const rs = []
          if (m.official_input > 0) rs.push(m.input_price / m.official_input)
          if (m.official_output > 0) rs.push(m.output_price / m.official_output)
          return rs.length ? Math.min(...rs) : null
        })
        .filter((x) => x !== null)
      if (ds.length) discountLabel.value = Math.round(Math.min(...ds) * 100) / 10 + ' 折'
    }
    pricePreview.value = catalog.slice(0, 6)
  } catch { /* 站点信息加载失败时使用内置默认 */ }
})
</script>

<style>
/* 折叠面板默认无左右内边距,文字会贴着白底左缘;统一撑出留白 */
.faq-collapse .el-collapse-item__header { font-weight: 600; font-size: 15px; padding: 0 20px; }
.faq-collapse .el-collapse-item__content { padding: 0 20px 22px; }
</style>
