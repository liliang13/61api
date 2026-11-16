<template>
  <div class="min-h-screen bg-white pt-[64px]">
    <SiteNav />
    <div class="mx-auto max-w-6xl gap-8 px-4 py-12 md:flex">
      <!-- 侧目录 -->
      <aside class="mb-8 w-full shrink-0 md:mb-0 md:w-52">
        <div class="sticky top-24 space-y-1">
          <a v-for="s in sections" :key="s.id" :href="`#${s.id}`"
            class="block rounded-lg px-3 py-2 text-sm font-medium text-stone-500 hover:bg-[#eef2ff] hover:text-[#4f46e5]">
            {{ s.label }}
          </a>
        </div>
      </aside>

      <main class="min-w-0 flex-1 space-y-14">
        <!-- 快速开始 -->
        <section id="quickstart">
          <h1 class="text-3xl font-bold text-stone-800">接入指南</h1>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            本站提供 <b>OpenAI / Anthropic / OpenAI Responses</b> 三种协议标准,改 Base URL 与密钥即可迁移。
            统一入口:<code class="rounded bg-[#eef2ff] px-1.5 py-0.5 font-mono text-xs text-[#4f46e5]">{{ apiBase }}</code>
          </p>
          <div class="mt-6 code-window overflow-hidden">
            <div class="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
              <div class="ml-1 flex gap-1">
                <button v-for="lang in Object.keys(samples)" :key="lang" @click="active = lang"
                  class="rounded-md px-3 py-1 text-xs font-semibold"
                  :class="active === lang ? 'bg-white/15 text-white' : 'text-stone-400 hover:text-white'">{{ lang }}</button>
              </div>
            </div>
            <pre class="codeblock" v-html="samples[active]"></pre>
          </div>
        </section>

        <!-- 接口总览 -->
        <section id="endpoints">
          <h2 class="text-2xl font-bold text-stone-800">接口总览</h2>
          <div class="mt-5 overflow-hidden rounded-2xl border border-black/5">
            <table class="w-full text-sm">
              <thead class="bg-[#fafafa] text-left text-xs text-stone-500">
                <tr>
                  <th class="px-4 py-2.5 font-semibold">方法</th>
                  <th class="px-4 py-2.5 font-semibold">路径</th>
                  <th class="px-4 py-2.5 font-semibold">说明</th>
                  <th class="px-4 py-2.5 font-semibold">协议标准</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-black/5 bg-white">
                <tr v-for="e in endpointTable" :key="e.path">
                  <td class="px-4 py-2.5">
                    <span class="rounded px-2 py-0.5 font-mono text-[11px] font-bold text-white"
                      :class="e.method === 'GET' ? 'bg-[#16a34a]' : 'bg-[#4f46e5]'">{{ e.method }}</span>
                  </td>
                  <td class="px-4 py-2.5"><code class="font-mono text-xs">{{ e.path }}</code></td>
                  <td class="px-4 py-2.5 text-xs text-stone-600">{{ e.desc }}</td>
                  <td class="px-4 py-2.5 text-xs text-stone-400">{{ e.std }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- 鉴权 -->
        <section id="auth">
          <h2 class="text-2xl font-bold text-stone-800">鉴权</h2>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            所有接口使用控制台生成的 <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono text-xs">sk-</code> 密钥。支持两种请求头写法:
          </p>
          <pre class="codeblock mt-4 rounded-xl bg-[#1e1e2e]">Authorization: Bearer sk-xxxx        <span class="text-stone-500"># OpenAI 客户端默认</span>
x-api-key: sk-xxxx                   <span class="text-stone-500"># Anthropic 客户端默认</span></pre>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            密钥可单独设置额度上限与启停;调用失败不产生费用。请妥善保管密钥,泄露请立即在控制台禁用并新建。
          </p>
        </section>

        <!-- Anthropic 兼容 -->
        <section id="anthropic">
          <h2 class="text-2xl font-bold text-stone-800">Anthropic 兼容(Claude Code / Cline 直连)</h2>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono text-xs">POST /v1/messages</code> 完整支持 Anthropic Messages 协议
            (system / max_tokens / 流式事件 message_start → content_block_delta → message_stop),鉴权兼容 x-api-key。
          </p>
          <div class="mt-5 grid gap-4 md:grid-cols-2">
            <div class="rounded-2xl border border-black/5 bg-[#fafafa] p-5">
              <p class="text-sm font-bold text-stone-800">Claude Code</p>
              <pre class="mt-3 overflow-x-auto rounded-lg bg-[#1e1e2e] p-3 font-mono text-xs leading-6 text-[#a5d6ff]">export ANTHROPIC_BASE_URL={{ apiOrigin }}
export ANTHROPIC_API_KEY=sk-你的密钥
claude  <span class="text-stone-500"># 直接使用</span></pre>
            </div>
            <div class="rounded-2xl border border-black/5 bg-[#fafafa] p-5">
              <p class="text-sm font-bold text-stone-800">通用 SDK(Python)</p>
              <pre class="mt-3 overflow-x-auto rounded-lg bg-[#1e1e2e] p-3 font-mono text-xs leading-6 text-[#a5d6ff]">from anthropic import Anthropic
c = Anthropic(api_key="sk-...", base_url="{{ apiOrigin }}")
m = c.messages.create(model="deepseek-flash",
    max_tokens=1024, messages=[{"role": "user",
    "content": "你好"}])</pre>
            </div>
          </div>
        </section>

        <!-- Responses -->
        <section id="responses">
          <h2 class="text-2xl font-bold text-stone-800">Responses 接口(新工具)</h2>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono text-xs">POST /v1/responses</code> 支持 OpenAI Responses 协议的无状态文本子集
            (instructions / input / max_output_tokens / 流式 response.output_text.delta),适配 Codex CLI 等新一代客户端。
          </p>
          <pre class="codeblock mt-4 rounded-xl bg-[#1e1e2e]">curl {{ apiBase }}/responses \
  -H "Authorization: Bearer sk-..." \
  -d '{"model": "deepseek-flash", "input": "你好", "stream": true}'</pre>
        </section>

        <!-- 向量 -->
        <section id="embeddings">
          <h2 class="text-2xl font-bold text-stone-800">向量接口(Embeddings)</h2>
          <p class="mt-3 text-sm leading-7 text-stone-500">
            <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono text-xs">POST /v1/embeddings</code>,入参
            <code class="rounded bg-black/5 px-1.5 py-0.5 font-mono text-xs">input</code> 支持字符串或数组(批量),按输入 Token 计费。
          </p>
          <pre class="codeblock mt-4 rounded-xl bg-[#1e1e2e]">vec = client.embeddings.create(
    model="text-embedding-3-small",
    input=["文本一", "文本二"],  <span class="text-stone-500"># 批量</span>
)</pre>
        </section>

        <!-- 工具配置 -->
        <section id="tools">
          <h2 class="text-2xl font-bold text-stone-800">常用工具配置</h2>
          <div class="mt-5 overflow-hidden rounded-2xl border border-black/5">
            <el-table :data="toolRows" style="width: 100%">
              <el-table-column prop="tool" label="工具" width="150" />
              <el-table-column prop="field" label="配置项" width="200" />
              <el-table-column label="填入值">
                <template #default="{ row }">
                  <code class="font-mono text-xs text-[#4f46e5]">{{ row.value }}</code>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <!-- 计费 -->
        <section id="billing">
          <h2 class="text-2xl font-bold text-stone-800">计费说明</h2>
          <ul class="mt-4 list-disc space-y-2 pl-5 text-sm leading-7 text-stone-500">
            <li>按 Token 计量,人民币计价:费用 = 输入 Token × 输入单价 + 输出 Token × 输出单价(单价见<a href="/models" class="font-semibold text-[#4f46e5] hover:underline">模型列表</a>,¥/百万 Tokens)。</li>
            <li>每次调用按<b>当时单价快照</b>落账,控制台「用量与计费明细」可逐笔复算(输入/输出分项、单价、公式),调价不影响历史账单。</li>
            <li>调用结束实时扣费;失败请求(含渠道故障自动切换期间的尝试)不产生费用。单次最低计费 1 quota(¥0.000002)。</li>
            <li>余额永不过期;<template v-if="store.isPrivate">额度由管理员在「用户管理」中分配,组织额度是成员可用额度的上限。</template><template v-else>充值 1 元 = 1 元额度,套餐含赠送比例;支持兑换码。</template></li>
            <li v-if="!store.isPrivate">按充值金额可申请开票(电子普票/增值税专票),支持多单合并;注意<b>已开票的充值不可退款</b>。</li>
          </ul>
        </section>

        <!-- 错误码 -->
        <section id="errors">
          <h2 class="text-2xl font-bold text-stone-800">错误码</h2>
          <div class="mt-5 overflow-hidden rounded-2xl border border-black/5">
            <el-table :data="errorRows" style="width: 100%">
              <el-table-column prop="code" label="HTTP 状态码" width="120" />
              <el-table-column prop="type" label="type" width="220" />
              <el-table-column prop="meaning" label="含义与处理" />
            </el-table>
          </div>
        </section>

        <!-- FAQ -->
        <section id="faq">
          <h2 class="text-2xl font-bold text-stone-800">常见问题</h2>
          <div class="mt-5 overflow-hidden rounded-2xl border border-black/5 bg-white">
            <el-collapse class="docs-collapse">
              <el-collapse-item v-for="q in faqs" :key="q.q" :title="q.q" :name="q.q">
                <p class="text-sm leading-7 text-stone-500">{{ q.a }}</p>
              </el-collapse-item>
            </el-collapse>
          </div>
        </section>
      </main>
    </div>
    <SiteFooter />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import SiteNav from '../components/SiteNav.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { API_ORIGIN, API_BASE_URL } from '../apiOrigin'
import { useUserStore } from '../stores/user'

const store = useUserStore()

const apiOrigin = API_ORIGIN
const apiBase = API_BASE_URL

const sections = [
  { id: 'quickstart', label: '快速开始' },
  { id: 'endpoints', label: '接口总览' },
  { id: 'auth', label: '鉴权' },
  { id: 'anthropic', label: 'Anthropic 兼容' },
  { id: 'responses', label: 'Responses 接口' },
  { id: 'embeddings', label: '向量接口' },
  { id: 'tools', label: '工具配置' },
  { id: 'billing', label: '计费说明' },
  { id: 'errors', label: '错误码' },
  { id: 'faq', label: '常见问题' },
]

const samples = {
  Python: `<span class="text-[#c586c0]">from</span> openai <span class="text-[#c586c0]">import</span> OpenAI

client = OpenAI(api_key=<span class="text-[#ce9178]">"sk-..."</span>, base_url=<span class="text-[#ce9178]">"${apiBase}"</span>)

<span class="text-stone-500"># 普通调用</span>
resp = client.chat.completions.create(
    model=<span class="text-[#ce9178]">"deepseek-flash"</span>,
    messages=[{<span class="text-[#ce9178]">"role"</span>: <span class="text-[#ce9178]">"user"</span>, <span class="text-[#ce9178]">"content"</span>: <span class="text-[#ce9178]">"你好"</span>}],
)

<span class="text-stone-500"># 流式调用</span>
stream = client.chat.completions.create(
    model=<span class="text-[#ce9178]">"deepseek-flash"</span>, messages=[...], stream=<span class="text-[#569cd6]">True</span>,
)
<span class="text-[#c586c0]">for</span> chunk <span class="text-[#c586c0]">in</span> stream:
    <span class="text-[#dcdcaa]">print</span>(chunk.choices[0].delta.content or <span class="text-[#ce9178]">""</span>, end=<span class="text-[#ce9178]">""</span>)`,
  'Node.js': `<span class="text-[#c586c0]">import</span> OpenAI <span class="text-[#c586c0]">from</span> <span class="text-[#ce9178]">"openai"</span>;

<span class="text-[#c586c0]">const</span> client = <span class="text-[#c586c0]">new</span> <span class="text-[#dcdcaa]">OpenAI</span>({ apiKey: <span class="text-[#ce9178]">"sk-..."</span>, baseURL: <span class="text-[#ce9178]">"${apiBase}"</span> });

<span class="text-[#c586c0]">const</span> stream = <span class="text-[#c586c0]">await</span> client.chat.completions.<span class="text-[#dcdcaa]">create</span>({
  model: <span class="text-[#ce9178]">"deepseek-flash"</span>,
  messages: [{ role: <span class="text-[#ce9178]">"user"</span>, content: <span class="text-[#ce9178]">"你好"</span> }],
  stream: <span class="text-[#569cd6]">true</span>,
});
<span class="text-[#c586c0]">for</span> <span class="text-[#c586c0]">await</span> (<span class="text-[#c586c0]">const</span> chunk <span class="text-[#c586c0]">of</span> stream) {
  process.stdout.<span class="text-[#dcdcaa]">write</span>(chunk.choices[0]?.delta?.content ?? <span class="text-[#ce9178]">""</span>);
}`,
  cURL: `curl ${apiBase}/chat/completions \\
  -H <span class="text-[#ce9178]">"Content-Type: application/json"</span> \\
  -H <span class="text-[#ce9178]">"Authorization: Bearer sk-..."</span> \\
  -d <span class="text-[#ce9178]">'{"model": "deepseek-flash", "stream": true,
    "messages": [{"role": "user", "content": "你好"}]}'</span>`,
}
const active = ref('Python')

const endpointTable = [
  { method: 'POST', path: '/v1/chat/completions', desc: '对话补全 · 流式/非流式', std: 'OpenAI Chat' },
  { method: 'POST', path: '/v1/messages', desc: '对话补全 · Claude Code 直连', std: 'Anthropic Messages' },
  { method: 'POST', path: '/v1/responses', desc: '对话补全 · 新一代客户端', std: 'OpenAI Responses' },
  { method: 'POST', path: '/v1/embeddings', desc: '文本向量化', std: 'OpenAI' },
  { method: 'GET', path: '/v1/models', desc: '模型列表', std: 'OpenAI' },
]

const toolRows = [
  { tool: 'Claude Code', field: 'ANTHROPIC_BASE_URL', value: apiOrigin },
  { tool: 'Claude Code', field: 'ANTHROPIC_API_KEY', value: '控制台生成的 sk- 密钥' },
  { tool: 'Cursor / Continue', field: 'Override Base URL', value: apiBase },
  { tool: 'Cline / Roo Code', field: 'Base URL(API Provider)', value: apiBase },
  { tool: 'Dify', field: 'OpenAI-API-compatible', value: apiBase },
  { tool: 'LobeChat / NextChat', field: '接口代理地址', value: apiBase },
  { tool: 'Cherry Studio', field: 'API Host', value: apiOrigin },
]

const errorRows = [
  { code: '401', type: 'authentication_error', meaning: '密钥无效或已禁用,到控制台检查密钥状态' },
  { code: '402', type: 'insufficient_quota', meaning: '余额不足或密钥额度用尽,请充值或调整密钥限额' },
  { code: '404', type: 'invalid_request_error', meaning: '模型不存在或未开放,对照模型列表' },
  { code: '428', type: 'precondition_required', meaning: '人机验证未通过(发短信验证码场景),重新完成验证' },
  { code: '429', type: 'rate_limit_error', meaning: '请求过于频繁(登录/发码有限流),稍后再试' },
  { code: '502', type: 'api_error', meaning: '所有上游渠道均不可用(已自动切换仍失败),稍后重试或联系管理员' },
  { code: '503', type: 'api_error', meaning: '无可用渠道,请联系管理员' },
]

const faqs = computed(() => [
  { q: '如何获取 API Key?', a: store.isPrivate
    ? '账号由管理员统一开通。登录控制台后,进入「API 密钥」页面点击「新建密钥」即可生成 sk- 开头的密钥;密钥仅在创建时完整展示一次。'
    : '注册并登录后,进入控制台「API 密钥」页面,点击「新建密钥」即可生成 sk- 开头的密钥。密钥仅在创建时完整展示一次,请妥善保存;可为每个密钥单独设置额度上限。' },
  { q: '和 OpenAI / Anthropic SDK 完全兼容吗?', a: '兼容。OpenAI SDK 用 chat.completions 与 embeddings;Anthropic SDK / Claude Code 把 base_url 指向本站即可;Responses 协议(Codex 等)同样支持。工具调用(function calling)暂未开放,需要的话联系我们。' },
  { q: '流式输出怎么用?', a: '请求体传 "stream": true 即可。三种协议的流式事件格式均与官方一致(OpenAI chunks / Anthropic message 事件 / Responses output_text.delta),SDK 无需特殊处理。' },
  { q: '渠道故障会中断我的调用吗?', a: '不会。网关内置故障自动切换:主渠道异常(超时/5xx/限流)当次请求立即切换备用渠道,用户无感;连续失败的渠道会被熔断 60 秒后自动探测恢复。' },
  { q: '如何计费?怎么核对账单?', a: '按 Token 计量、人民币计价。控制台「用量与计费明细」支持按时间/模型/密钥筛选,每笔调用展开可见单价快照与复算公式;调价不影响历史账单。失败请求不收费。' },
  ...(store.isPrivate ? [] : [{ q: '可以开发票吗?', a: '可以。控制台「发票管理」按充值订单金额申请,支持多单合并、企业/个人抬头、电子普票/增值税专票。注意:已申请开票的充值不可退款。' }]),
  { q: '调用报错怎么办?', a: '对照错误码表:401 检查密钥、402 检查余额、404 对照模型列表、502/503 为上游异常(通常自动重试即可)。仍无法解决请联系管理员。' },
])
</script>

<style>
.docs-collapse .el-collapse-item__header { font-weight: 600; font-size: 15px; padding: 0 20px; }
.docs-collapse .el-collapse-item__content { padding: 0 20px 22px; }
</style>
