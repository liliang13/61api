<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">渠道管理</h1>
      <div class="flex gap-2">
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openWizard">新增渠道</el-button>
      </div>
    </div>
    <p class="mt-2 text-xs text-stone-400">
      同优先级内按权重分流,数值小的优先级更高;探活异常的渠道会自动禁用并通知,恢复后自动上线。请求失败自动切换下一渠道,切换记录见渠道详情。
    </p>

    <!-- 状态总览 -->
    <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div v-for="card in summaryCards" :key="card.label"
           class="rounded-2xl border border-black/5 bg-white px-4 py-3">
        <p class="text-xs text-stone-400">{{ card.label }}</p>
        <p class="mt-1 text-2xl font-bold" :class="card.tone">{{ card.value }}</p>
      </div>
    </div>

    <div class="mt-4 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="channels" style="width: 100%">
        <el-table-column prop="id" label="ID" width="55" />
        <el-table-column label="名称" min-width="130">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="openDrawer(row)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.type === 'mock' ? 'info' : 'success'" effect="plain">{{ row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="健康" width="110" align="center">
          <template #default="{ row }">
            <el-tooltip :content="healthTip(row)" placement="top" :disabled="!healthTip(row)">
              <el-tag size="small" :type="healthOf(row).type" effect="plain">{{ healthOf(row).label }}</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="最近探活" width="160">
          <template #default="{ row }">
            <el-tooltip :content="row.last_test_error || ''" placement="top" :disabled="!row.last_test_error">
              <span class="text-xs" :class="row.last_test_ok === 0 ? 'text-[#dc2626]' : 'text-stone-600'">{{ probeText(row) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="余额" width="130">
          <template #default="{ row }">
            <el-tooltip v-if="row.last_balance_info" :content="balanceTip(row)" placement="top">
              <span class="text-xs font-semibold" :class="row.last_balance_info.balance <= 10 ? 'text-[#dc2626]' : 'text-stone-700'">
                ¥{{ row.last_balance_info.balance.toFixed(2) }}
                <span class="font-normal text-stone-400">{{ relTime(row.last_balance_at) }}</span>
              </span>
            </el-tooltip>
            <span v-else class="text-xs text-stone-300">未查询</span>
          </template>
        </el-table-column>
        <el-table-column label="24h 调用" width="110" align="center">
          <template #default="{ row }">
            <span class="text-xs text-stone-600">{{ row.usage_24h?.requests || 0 }} 次</span>
            <span v-if="row.usage_24h?.ok_rate != null" class="ml-1 text-xs"
                  :class="row.usage_24h.ok_rate >= 0.99 ? 'text-[#16a34a]' : 'text-[#dc2626]'">{{ pct(row.usage_24h.ok_rate) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="base_url" label="Base URL" min-width="150" show-overflow-tooltip />
        <el-table-column label="模型范围" min-width="120">
          <template #default="{ row }">
            <code class="font-mono text-xs">{{ row.models.slice(0, 3).join(', ') }}{{ row.models.length > 3 ? '…' : '' }}</code>
          </template>
        </el-table-column>
        <el-table-column label="优先级/权重" width="100" align="center">
          <template #default="{ row }"><span class="text-xs">{{ row.priority }} / {{ row.weight }}</span></template>
        </el-table-column>
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch :model-value="row.status === 1" @change="toggle(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :loading="testing === row.id" @click="test(row)">测通</el-button>
            <el-button link type="primary" size="small" :loading="balancing === row.id" @click="queryBalance(row)">查余额</el-button>
            <el-button link type="primary" size="small" @click="promote(row)">主用</el-button>
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 渠道详情与事件时间线 -->
    <el-drawer v-model="drawer.visible" :title="`渠道详情 · ${drawerChannel?.name || ''}`" size="480">
      <template v-if="drawerChannel">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="Base URL">{{ drawerChannel.base_url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API Key"><code class="font-mono text-xs">{{ drawerChannel.api_key }}</code></el-descriptions-item>
          <el-descriptions-item label="承接模型">
            <code class="font-mono text-xs">{{ drawerChannel.models.join(', ') }}</code>
          </el-descriptions-item>
          <el-descriptions-item v-if="Object.keys(drawerChannel.model_map || {}).length" label="模型映射">
            <code class="font-mono text-xs">{{ JSON.stringify(drawerChannel.model_map) }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="优先级/权重">{{ drawerChannel.priority }} / {{ drawerChannel.weight }}</el-descriptions-item>
          <el-descriptions-item label="24h 用量">
            {{ drawerChannel.usage_24h?.requests || 0 }} 次 · ¥{{ (drawerChannel.usage_24h?.quota_yuan ?? 0).toFixed(4) }}
            <template v-if="drawerChannel.usage_24h?.ok_rate != null"> · 成功率 {{ pct(drawerChannel.usage_24h.ok_rate) }}</template>
          </el-descriptions-item>
          <el-descriptions-item label="上游余额">
            <template v-if="drawerChannel.last_balance_info">
              ¥{{ drawerChannel.last_balance_info.balance.toFixed(2) }}
              (累计入账 ¥{{ Number(drawerChannel.last_balance_info.total || 0).toFixed(2) }},
              已用 ¥{{ Number(drawerChannel.last_balance_info.used || 0).toFixed(2) }}{{ drawerChannel.last_balance_at ? `,${relTime(drawerChannel.last_balance_at)}查询` : '' }})
            </template>
            <template v-else>未查询(列表页点「查余额」)</template>
          </el-descriptions-item>
        </el-descriptions>
        <div class="mt-4 flex items-center justify-between">
          <h3 class="text-sm font-bold text-stone-700">事件时间线</h3>
          <el-button size="small" @click="load">刷新事件</el-button>
        </div>
        <el-timeline v-if="drawerChannel.events?.length" class="mt-3">
          <el-timeline-item v-for="ev in drawerChannel.events" :key="ev.id"
                            :timestamp="ev.created_at" :type="EVENT_META[ev.kind]?.dot || 'info'">
            <p class="text-xs">
              <el-tag size="small" :type="EVENT_META[ev.kind]?.type || 'info'" effect="plain">{{ EVENT_META[ev.kind]?.label || ev.kind }}</el-tag>
              <span v-if="ev.latency_ms != null" class="ml-1 text-stone-400">{{ ev.latency_ms }}ms</span>
            </p>
            <p v-if="ev.message" class="mt-1 break-all text-xs text-stone-600">{{ ev.message }}</p>
            <p v-if="ev.request_id" class="mt-0.5 font-mono text-[10px] text-stone-400">req: {{ ev.request_id }}</p>
          </el-timeline-item>
        </el-timeline>
        <p v-else class="mt-3 text-xs text-stone-400">暂无事件。探活结果与请求失败切换都会记录在这里。</p>
      </template>
    </el-drawer>

    <!-- 新建渠道向导 -->
    <el-dialog v-model="wiz.visible" title="新增渠道向导" width="640" :close-on-click-modal="false">
      <el-steps :active="wiz.step - 1" align-center finish-status="success" class="mb-5">
        <el-step title="上游信息" />
        <el-step title="选择模型" />
        <el-step title="测试启用" />
      </el-steps>

      <el-form v-if="wiz.step === 1" label-position="top">
        <el-form-item label="渠道名称">
          <el-input v-model="wiz.form.name" placeholder="如:DeepSeek 官方" />
        </el-form-item>
        <el-form-item label="Base URL(OpenAI 兼容,如 https://api.upstream.com/v1)">
          <el-input v-model="wiz.form.base_url" placeholder="https://" />
        </el-form-item>
        <el-form-item label="上游 API Key">
          <el-input v-model="wiz.form.api_key" show-password placeholder="sk-…" />
        </el-form-item>
      </el-form>

      <div v-else-if="wiz.step === 2">
        <div class="flex items-center gap-2">
          <p class="text-xs text-stone-500">
            上游共 {{ wiz.upstream.length }} 个模型,点选要承接的(绿点=已在站内目录;
            <span class="text-[#4f46e5]">蓝字=已被其他渠道承接,共同承接即自动主备</span>)。
          </p>
          <el-button size="small" :loading="wiz.fetching" @click="fetchWizModels">重新拉取</el-button>
        </div>
        <div class="mt-3 max-h-64 overflow-y-auto rounded-xl border border-black/5 bg-[#fafafa] p-3">
          <div class="flex flex-wrap gap-2">
            <div v-for="m in wiz.upstream" :key="m.name" @click="toggleWizModel(m)"
                 class="flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors"
                 :class="wiz.picked.includes(m.name)
                   ? 'border-[#4f46e5] bg-[#eef2ff] text-[#4f46e5] font-semibold'
                   : 'border-black/10 bg-white text-stone-600'">
              <span class="h-1.5 w-1.5 rounded-full" :class="m.in_catalog ? 'bg-[#16a34a]' : 'bg-stone-300'"></span>
              <span :class="m.other_channels.length ? 'text-[#4f46e5]' : ''">{{ m.name }}</span>
              <span v-if="m.upstream_input != null" class="text-[10px] text-stone-400">¥{{ m.upstream_input }}/{{ m.upstream_output }}</span>
            </div>
            <p v-if="!wiz.upstream.length" class="text-xs text-stone-400">未拉取到模型列表,可返回上一步检查地址/密钥,或下一步手动填写。</p>
          </div>
        </div>
        <div class="mt-3 flex items-center justify-between rounded-xl border border-black/5 bg-white p-3">
          <p class="text-xs text-stone-500">
            未上架的选中模型 <b>{{ wizUnimported.length }}</b> 个,可按上游成本 ×1.5 一键上架(可在模型定价页再调整)。
          </p>
          <el-button size="small" type="success" :disabled="!wizUnimported.length" :loading="wiz.importing" @click="wizImportAll">
            一键上架
          </el-button>
        </div>
        <div v-if="wizMapped.length" class="mt-3 rounded-xl border border-black/5 bg-[#fafafa] p-3">
          <p class="mb-2 text-xs text-stone-500">
            模型映射:上游模型名与站内名不同时填「上游模型名」,转发时自动改名;留空 = 同名直发。
          </p>
          <div class="space-y-2">
            <div v-for="n in wizMapped" :key="n" class="flex items-center gap-2 text-xs">
              <code class="w-44 shrink-0 truncate font-mono text-stone-700">{{ n }}</code>
              <span class="shrink-0 text-stone-400">→</span>
              <el-input v-model="wiz.mapInputs[n]" size="small" :placeholder="`${n}(同名直发)`" />
            </div>
          </div>
        </div>
      </div>

      <div v-else class="space-y-3">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="名称">{{ wiz.form.name }}</el-descriptions-item>
          <el-descriptions-item label="Base URL">{{ wiz.form.base_url }}</el-descriptions-item>
          <el-descriptions-item label="承接模型">
            <code class="font-mono text-xs">{{ wiz.picked.length ? wiz.picked.join(', ') : '*(全部)' }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="优先级/权重">{{ wiz.form.priority }} / {{ wiz.form.weight }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="wiz.testResult" :type="wiz.testResult.ok ? 'success' : 'error'" :closable="false"
                  :title="wiz.testResult.ok
                    ? `测通成功(测试模型 ${wiz.testResult.model}),耗时 ${wiz.testResult.latency_ms}ms`
                    : `测通失败[${wiz.testResult.model}]:${wiz.testResult.error}`" />
      </div>

      <template #footer>
        <el-button v-if="wiz.step > 1" @click="wiz.step -= 1">上一步</el-button>
        <el-button v-if="wiz.step === 1" type="primary" :loading="wiz.fetching" @click="wizNext">下一步:拉取模型</el-button>
        <el-button v-else-if="wiz.step === 2" type="primary" @click="wiz.step = 3">下一步:测试启用</el-button>
        <el-button v-else-if="!wiz.createdId" type="primary" :loading="wiz.saving || wiz.testing" @click="wizSave">
          保存并测通
        </el-button>
        <el-button v-else type="primary" @click="wiz.visible = false">完成</el-button>
      </template>
    </el-dialog>

    <!-- 编辑渠道 -->
    <el-dialog v-model="dlg.visible" title="编辑渠道" width="560">
      <el-form label-position="top">
        <div class="grid grid-cols-2 gap-3">
          <el-form-item label="渠道名称"><el-input v-model="dlg.form.name" placeholder="如:官方直连" /></el-form-item>
          <el-form-item label="类型">
            <el-select v-model="dlg.form.type" class="w-full">
              <el-option label="openai(OpenAI 兼容上游)" value="openai" />
              <el-option label="mock(内置演示)" value="mock" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item v-if="dlg.form.type === 'openai'" label="Base URL(如 https://api.upstream.com/v1)">
          <el-input v-model="dlg.form.base_url" />
        </el-form-item>
        <el-form-item v-if="dlg.form.type === 'openai'" label="上游 API Key(留空 = 保持已保存的密钥不变)">
          <el-input v-model="dlg.form.api_key" show-password placeholder="留空保持原值,填写则覆盖" />
        </el-form-item>
        <el-form-item label="承接的站内模型(多选;同名模型多渠道承接即自动互为主备)">
          <div class="w-full">
            <div class="flex w-full gap-2">
              <el-select v-model="dlg.form.models" multiple filterable allow-create default-first-option
                         placeholder="从站内模型列表选择;输入可新建;* 表示承接全部" class="!w-full">
                <el-option label="*(承接全部模型)" value="*" />
                <el-option v-for="m in catalogNames" :key="m" :label="m" :value="m" />
              </el-select>
              <el-button :loading="fetchingModels" :disabled="!dlg.editId" @click="fetchUpstreamModels">
                {{ fetchingModels ? '拉取中…' : '从上游拉取模型' }}
              </el-button>
            </div>
            <div v-if="upstreamModels.length" class="mt-3 max-h-56 overflow-y-auto rounded-xl border border-black/5 bg-[#fafafa] p-3">
              <p class="mb-2 text-xs text-stone-500">
                上游共 {{ upstreamModels.length }} 个模型,勾选后自动填入(绿点=已在站内目录;
                <span class="text-[#4f46e5]">蓝字=已被其他渠道承接,共同承接即自动主备切换</span>):
              </p>
              <div class="flex flex-wrap gap-2">
                <div v-for="m in upstreamModels" :key="m.name" @click="toggleUpstream(m.name)"
                  class="flex cursor-pointer items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors"
                  :class="upstreamPicked.includes(m.name)
                    ? 'border-[#4f46e5] bg-[#eef2ff] text-[#4f46e5] font-semibold'
                    : 'border-black/10 bg-white text-stone-600'">
                  <span class="h-1.5 w-1.5 rounded-full" :class="m.in_catalog ? 'bg-[#16a34a]' : 'bg-stone-300'"></span>
                  <span :class="m.other_channels.length ? 'text-[#4f46e5]' : ''">{{ m.name }}</span>
                  <span v-if="m.upstream_input != null" class="text-[10px] text-stone-400">
                    ¥{{ m.upstream_input }}/{{ m.upstream_output }}
                    <span v-if="m.upstream_cache != null" class="text-[#16a34a]">(缓存¥{{ m.upstream_cache }})</span>
                  </span>
                  <span v-if="!m.in_catalog" @click.stop="openImport(m)"
                    class="rounded bg-[#16a34a]/10 px-1.5 py-0.5 text-[10px] font-bold text-[#16a34a] hover:bg-[#16a34a]/20">+上架</span>
                  <el-tooltip v-if="m.other_channels.length" :content="'已由 ' + m.other_channels.join('、') + ' 承接'" placement="top">
                    <span class="rounded bg-[#4f46e5]/10 px-1 text-[10px] font-semibold text-[#4f46e5]">×{{ m.other_channels.length }}</span>
                  </el-tooltip>
                </div>
              </div>
            </div>
            <div v-if="mappedModels.length" class="mt-3 rounded-xl border border-black/5 bg-[#fafafa] p-3">
              <p class="mb-2 text-xs text-stone-500">
                模型映射:上游接口的模型名与站内名不同时,填「上游模型名」完成合并(请求转发时自动改名);
                留空 = 同名直发。
              </p>
              <div class="space-y-2">
                <div v-for="n in mappedModels" :key="n" class="flex items-center gap-2 text-xs">
                  <code class="w-44 shrink-0 truncate font-mono text-stone-700">{{ n }}</code>
                  <span class="shrink-0 text-stone-400">→</span>
                  <el-input v-model="mapInputs[n]" size="small" :placeholder="`${n}(同名直发)`" />
                </div>
              </div>
            </div>
          </div>
        </el-form-item>
        <div class="grid grid-cols-3 gap-3">
          <el-form-item label="优先级(小者优先)"><el-input-number v-model="dlg.form.priority" class="!w-full" /></el-form-item>
          <el-form-item label="权重"><el-input-number v-model="dlg.form.weight" :min="1" class="!w-full" /></el-form-item>
          <el-form-item label="启用"><el-switch v-model="dlg.form.status" /></el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dlg.visible = false">取消</el-button>
        <el-button type="primary" :loading="dlg.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 上架模型定价弹窗 -->
    <el-dialog v-model="imp.visible" :title="`上架模型 · ${imp.name}`" width="420">
      <p class="mb-3 text-xs text-stone-400">
        该模型尚未在定价目录中,填写售价(¥/百万 Tokens)后立即上架可售。
        <template v-if="imp.upstream">
          <br>上游成本价:¥{{ imp.upstream[0] }} / ¥{{ imp.upstream[1] }}(建议售价已按成本 ×1.5 预填,可调整)
        </template>
      </p>
      <el-form label-position="top">
        <el-form-item label="输入价 ¥/1M"><el-input-number v-model="imp.input_price" :min="0.01" :precision="3" :step="0.5" class="!w-full" /></el-form-item>
        <el-form-item label="输出价 ¥/1M"><el-input-number v-model="imp.output_price" :min="0" :precision="3" :step="0.5" class="!w-full" /></el-form-item>
        <el-form-item label="缓存命中输入价 ¥/1M(0=按全价)">
          <el-input-number v-model="imp.cache_input_price" :min="0" :precision="3" :step="0.5" class="!w-full" />
        </el-form-item>
        <el-form-item label="厂商"><el-input v-model="imp.vendor" maxlength="32" /></el-form-item>
        <el-form-item label="标签(逗号分隔,已按上游能力自动生成)">
          <el-input v-model="tagsText" placeholder="推理, 编码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="imp.visible = false">取消</el-button>
        <el-button type="primary" :loading="imp.saving" @click="submitImport">上架</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminChannelBalance, adminChannelOverview, adminCreateChannel, adminDeleteChannel, adminImportModel, adminModels,
  adminProbeModels, adminPromoteChannel, adminTestChannel, adminUpdateChannel, adminUpstreamModels,
} from '../../api'
import { dialogResult } from '../../utils/dialog'
import { latency, pct, relTime } from '../../utils/format'

const EVENT_META = {
  probe_ok: { label: '探活成功', type: 'success', dot: 'success' },
  probe_fail: { label: '探活失败', type: 'warning', dot: 'warning' },
  auto_disable: { label: '自动禁用', type: 'danger', dot: 'danger' },
  auto_recover: { label: '自动恢复', type: 'success', dot: 'success' },
  failover: { label: '请求切换', type: 'warning', dot: 'warning' },
}

const channels = ref([])
const summary = ref({})
const testing = ref(null)
const balancing = ref(null)
let timer = null

const summaryCards = computed(() => [
  { label: '总渠道', value: summary.value.total ?? 0, tone: 'text-stone-800' },
  { label: '启用中', value: summary.value.enabled ?? 0, tone: 'text-[#16a34a]' },
  { label: '熔断中', value: summary.value.circuit_open ?? 0, tone: (summary.value.circuit_open ?? 0) ? 'text-[#dc2626]' : 'text-stone-800' },
  { label: '自动禁用', value: summary.value.auto_disabled ?? 0, tone: (summary.value.auto_disabled ?? 0) ? 'text-[#dc2626]' : 'text-stone-800' },
  { label: '未测过', value: summary.value.untested ?? 0, tone: 'text-stone-500' },
])

function healthOf(row) {
  if (row.type === 'mock') return { label: '演示', type: 'info' }
  if (row.circuit_open) return { label: `熔断 ${row.circuit_left}s`, type: 'danger' }
  if (row.auto_disabled === 1) return { label: '已自动禁用', type: 'danger' }
  if (row.status === 0) return { label: '手动停用', type: 'info' }
  if (row.last_test_ok === 1) return { label: '正常', type: 'success' }
  if (row.last_test_ok === 0) return { label: '探活失败', type: 'warning' }
  return { label: '未测过', type: 'info' }
}

function healthTip(row) {
  const parts = []
  if (row.fail_streak > 0) parts.push(`连续失败 ${row.fail_streak} 次`)
  if (row.recent_fails > 0) parts.push(`进程内连续出错 ${row.recent_fails} 次`)
  if (row.last_test_error) parts.push(row.last_test_error)
  if (row.last_err && row.last_err !== row.last_test_error) parts.push(row.last_err)
  return parts.join(';')
}

function probeText(row) {
  if (row.type === 'mock') return '-'
  if (row.last_test_ok == null) return '未测过'
  return `${row.last_test_ok === 1 ? '✓' : '✗'} ${latency(row.last_test_latency_ms)} · ${relTime(row.last_test_at)}`
}

function balanceTip(row) {
  const b = row.last_balance_info
  if (!b) return ''
  const parts = [`累计入账 ¥${Number(b.total || 0).toFixed(2)}`, `已用 ¥${Number(b.used || 0).toFixed(2)}`]
  if (b.is_active === false) parts.push('账户已停用')
  if (row.last_balance_at) parts.push(`${relTime(row.last_balance_at)}查询`)
  return parts.join(' · ')
}

async function queryBalance(row) {
  balancing.value = row.id
  try {
    const res = await adminChannelBalance(row.id)
    ElMessage.success(`「${row.name}」余额 ¥${res.data.balance.toFixed(2)}(${res.data.currency})`)
    await load()
  } finally { balancing.value = null }
}

// ---------------- 渠道详情抽屉 ----------------
const drawer = reactive({ visible: false, id: null })
const drawerChannel = computed(() => channels.value.find((c) => c.id === drawer.id))

function openDrawer(row) {
  drawer.id = row.id
  drawer.visible = true
}

// ---------------- 新建渠道向导 ----------------
const wiz = reactive({
  visible: false, step: 1, saving: false, fetching: false, importing: false, testing: false,
  testResult: null, createdId: null,
  form: { name: '', base_url: '', api_key: '', priority: 0, weight: 1 },
  upstream: [], picked: [], mapInputs: {},
})

const wizMapped = computed(() => wiz.picked.filter((n) => n && n !== '*'))
const wizUnimported = computed(() =>
  wiz.upstream.filter((m) => wiz.picked.includes(m.name) && !m.in_catalog))

function openWizard() {
  wiz.step = 1
  wiz.visible = true
  wiz.testResult = null
  wiz.createdId = null
  wiz.upstream = []
  wiz.picked = []
  wiz.mapInputs = {}
  wiz.form = { name: '', base_url: '', api_key: '', priority: 0, weight: 1 }
}

async function fetchWizModels() {
  if (!wiz.form.name.trim()) return ElMessage.warning('请先填写渠道名称')
  if (!wiz.form.base_url.trim()) return ElMessage.warning('请先填写 Base URL')
  wiz.fetching = true
  try {
    const res = await adminProbeModels({ base_url: wiz.form.base_url.trim(), api_key: wiz.form.api_key.trim() })
    wiz.upstream = res.data.models
    if (res.data.models.length) ElMessage.success(`拉取到 ${res.data.models.length} 个上游模型,点选要承接的`)
    else ElMessage.warning('上游未返回任何模型,请检查地址与密钥')
  } finally { wiz.fetching = false }
}

function toggleWizModel(m) {
  const i = wiz.picked.indexOf(m.name)
  if (i >= 0) wiz.picked.splice(i, 1)
  else wiz.picked.push(m.name)
}

async function wizImportAll() {
  wiz.importing = true
  try {
    let done = 0
    for (const m of wizUnimported.value) {
      await adminImportModel({
        name: m.name,
        input_price: m.upstream_input != null ? +(m.upstream_input * 1.5).toFixed(2) : 1,
        output_price: m.upstream_output != null ? +(m.upstream_output * 1.5).toFixed(2) : 4,
        cache_input_price: m.upstream_cache != null ? +(m.upstream_cache * 1.5).toFixed(2) : 0,
        vendor: wiz.form.name.trim() || '其他',
        tags: (m.upstream_tags && m.upstream_tags.length) ? m.upstream_tags : ['对话'],
      })
      done += 1
    }
    ElMessage.success(`已上架 ${done} 个模型`)
    await fetchWizModels()
  } finally { wiz.importing = false }
}

async function wizSave() {
  wiz.saving = true
  try {
    // 只保留真的改名的映射;同名直发不入库
    const model_map = {}
    for (const n of wizMapped.value) {
      const v = String(wiz.mapInputs[n] || '').trim()
      if (v && v !== n) model_map[n] = v
    }
    const created = (await adminCreateChannel({
      name: wiz.form.name.trim(), type: 'openai',
      base_url: wiz.form.base_url.trim(), api_key: wiz.form.api_key.trim(),
      models: wiz.picked.length ? [...wiz.picked] : ['*'],
      model_map, priority: wiz.form.priority, weight: wiz.form.weight, status: 1,
    })).data
    wiz.createdId = created.id
    wiz.testing = true
    const res = await adminTestChannel(created.id)
    wiz.testResult = res.data
    await load()
  } finally { wiz.saving = false; wiz.testing = false }
}

// ---------------- 编辑渠道(含模型映射) ----------------
const dlg = reactive({
  visible: false, editId: null, saving: false,
  form: { name: '', type: 'openai', base_url: '', api_key: '', models: ['*'], model_map: {}, priority: 0, weight: 1, status: true },
})
const imp = reactive({ visible: false, saving: false, name: '', input_price: 1, output_price: 4, cache_input_price: 0, vendor: '', upstream: null, tags: [] })

// 站内模型目录(用于「承接的站内模型」下拉与合并映射)
const catalogModels = ref([])
const catalogNames = computed(() => catalogModels.value.map((m) => m.name))
async function loadCatalog() {
  try { catalogModels.value = (await adminModels()).data || [] } catch { catalogModels.value = [] }
}

// 合并映射:站内名 → 上游模型名(留空 = 同名直发)
const mapInputs = ref({})
const mappedModels = computed(() => (dlg.form.models || []).filter((n) => n && n !== '*'))

function openImport(m) {
  imp.name = m.name
  imp.upstream = m.upstream_input != null ? [m.upstream_input, m.upstream_output] : null
  // 建议售价:有上游价则 ×1.5(默认 50% 毛利),否则用默认占位
  imp.input_price = m.upstream_input != null ? +(m.upstream_input * 1.5).toFixed(2) : 1
  imp.output_price = m.upstream_output != null ? +(m.upstream_output * 1.5).toFixed(2) : 4
  imp.cache_input_price = m.upstream_cache != null ? +(m.upstream_cache * 1.5).toFixed(2) : 0
  imp.tags = (m.upstream_tags && m.upstream_tags.length) ? [...m.upstream_tags] : ['对话']
  imp.vendor = dlg.form.name || ''
  imp.visible = true
}

const tagsText = computed({
  get: () => (imp.tags || []).join(', '),
  set: (v) => { imp.tags = v.split(/[,，]/).map((x) => x.trim()).filter(Boolean) },
})

async function submitImport() {
  imp.saving = true
  try {
    await adminImportModel({ name: imp.name, input_price: imp.input_price,
      output_price: imp.output_price, cache_input_price: imp.cache_input_price,
      vendor: imp.vendor, tags: imp.tags })
    ElMessage.success(`「${imp.name}」已上架,可在模型定价页调整`)
    imp.visible = false
    // 刷新拉取列表的目录标记与站内模型下拉
    await loadCatalog()
    if (dlg.editId) await fetchUpstreamModels()
  } finally { imp.saving = false }
}

const upstreamModels = ref([])
const upstreamPicked = ref([])
const fetchingModels = ref(false)

async function fetchUpstreamModels() {
  fetchingModels.value = true
  upstreamModels.value = []
  try {
    const res = await adminUpstreamModels(dlg.editId)
    upstreamModels.value = res.data.models.filter((m) => m.name !== '*')
    upstreamPicked.value = [...(dlg.form.models || [])].filter((n) => n !== '*')
  } finally { fetchingModels.value = false }
}

function toggleUpstream(name) {
  const i = upstreamPicked.value.indexOf(name)
  if (i >= 0) upstreamPicked.value.splice(i, 1)
  else upstreamPicked.value.push(name)
  // 勾选即覆盖 "*",与后端空列表兜底为 ["*"] 的语义保持一致
  dlg.form.models = upstreamPicked.value.length ? [...upstreamPicked.value] : ['*']
}

async function load() {
  const res = await adminChannelOverview()
  channels.value = res.data.items
  summary.value = res.data.summary
}

function openEdit(row) {
  dlg.editId = row.id
  dlg.form = { ...row, api_key: '', status: row.status === 1, model_map: row.model_map || {} }
  mapInputs.value = { ...(row.model_map || {}) }
  upstreamModels.value = []
  dlg.visible = true
}

async function save() {
  if (!dlg.form.name) return ElMessage.warning('请填写渠道名称')
  if (dlg.form.type === 'openai' && !dlg.editId && !dlg.form.base_url) return ElMessage.warning('请填写 Base URL')
  // 只保留真的改名的映射;同名直发不入库
  const model_map = {}
  for (const n of mappedModels.value) {
    const v = String(mapInputs.value[n] || '').trim()
    if (v && v !== n) model_map[n] = v
  }
  dlg.form.model_map = model_map
  dlg.saving = true
  try {
    await adminUpdateChannel(dlg.editId, dlg.form)
    ElMessage.success('已保存')
    dlg.visible = false
    await load()
  } finally { dlg.saving = false }
}

async function toggle(row) {
  await adminUpdateChannel(row.id, { status: row.status === 1 ? 0 : 1 })
  await load()
}

async function promote(row) {
  await adminPromoteChannel(row.id)
  ElMessage.success(`「${row.name}」已设为主用(优先级最高)`)
  await load()
}

async function test(row) {
  testing.value = row.id
  try {
    const res = await adminTestChannel(row.id)
    if (res.data.ok) ElMessage.success(`测通成功(测试模型 ${res.data.model}),耗时 ${res.data.latency_ms}ms`)
    else ElMessage.error(`测通失败[${res.data.model}]:${res.data.error}`)
    await load()
  } finally { testing.value = null }
}

async function remove(row) {
  if (!await dialogResult(ElMessageBox.confirm(`确定删除渠道「${row.name}」?`, '删除确认', { type: 'warning' }))) return
  await adminDeleteChannel(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(() => {
  load()
  loadCatalog()
  timer = setInterval(load, 30000)   // 状态页轻量轮询,关页即停
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>
