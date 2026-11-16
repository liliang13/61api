<template>
  <div class="min-h-screen bg-[#fafafa] pt-[64px]">
    <SiteNav />
    <div class="mx-auto max-w-6xl px-4 py-12">
      <h1 class="text-3xl font-bold text-stone-800">模型列表</h1>
      <p class="mt-2 text-sm text-stone-500">{{ store.isPrivate ? '全部模型均可通过同一个 API Key 调用 · 单价为内部结算价(每百万 Tokens,人民币)' : '全部模型均可通过同一个 API Key 调用 · 单价为每百万 Tokens(人民币)' }}</p>

      <!-- 厂商筛选(可多选,重复点击取消)+ 搜索 -->
      <div class="mt-8 flex flex-wrap items-center gap-2">
        <button @click="clearVendor"
          class="rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors"
          :class="!selectedVendors.length
            ? 'border-[#4f46e5] bg-[#4f46e5] text-white'
            : 'border-black/10 bg-white text-stone-600 hover:border-[#4f46e5]/40 hover:text-[#4f46e5]'">
          全部
        </button>
        <button v-for="v in vendors" :key="v" @click="toggleVendor(v)"
          class="rounded-full border px-3.5 py-1.5 text-sm font-semibold transition-colors"
          :class="selectedVendors.includes(v)
            ? 'border-[#4f46e5] bg-[#4f46e5] text-white'
            : 'border-black/10 bg-white text-stone-600 hover:border-[#4f46e5]/40 hover:text-[#4f46e5]'">
          {{ v }}<span class="ml-1 text-xs opacity-70">{{ vendorCount(v) }}</span>
        </button>
        <el-input v-model="keyword" placeholder="搜索模型名 / 显示名" clearable class="!w-56 ml-auto" :prefix-icon="Search" />
      </div>
      <p class="mt-3 text-xs text-stone-400">共 {{ filtered.length }} 个模型</p>

      <!-- 平铺卡片 -->
      <div class="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="m in filtered" :key="m.name" class="card-hover flex flex-col rounded-2xl border border-black/5 bg-white p-5">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="truncate text-base font-bold text-stone-800">{{ m.display_name }}</div>
              <div class="truncate font-mono text-xs text-stone-400">{{ m.name }}</div>
            </div>
            <span v-if="discountOf(m)"
              class="shrink-0 rounded-full bg-[#16a34a] px-2 py-0.5 text-xs font-bold text-white">{{ discountOf(m) }}</span>
          </div>
          <div v-if="m.tags && m.tags.length" class="mt-3 flex flex-wrap gap-1">
            <el-tag v-for="t in m.tags" :key="t" size="small" type="info" effect="plain">{{ t }}</el-tag>
          </div>
          <div class="mt-4 grid grid-cols-3 gap-1 rounded-xl bg-[#fafafa] p-3 text-center">
            <div>
              <p class="text-[11px] text-stone-400">输入 /1M</p>
              <p class="mt-0.5 whitespace-nowrap text-sm font-bold text-stone-700">
                ¥{{ m.input_price.toFixed(2) }}
                <span v-if="m.official_input > m.input_price" class="text-[10px] font-normal text-stone-300 line-through">¥{{ m.official_input.toFixed(2) }}</span>
              </p>
            </div>
            <div>
              <p class="text-[11px] text-stone-400">输出 /1M</p>
              <p class="mt-0.5 whitespace-nowrap text-sm font-bold text-stone-700">
                ¥{{ m.output_price.toFixed(2) }}
                <span v-if="m.official_output > m.output_price" class="text-[10px] font-normal text-stone-300 line-through">¥{{ m.official_output.toFixed(2) }}</span>
              </p>
            </div>
            <div>
              <p class="text-[11px] text-stone-400">缓存命中</p>
              <p v-if="m.cache_input_price > 0" class="mt-0.5 whitespace-nowrap text-sm font-bold text-[#16a34a]">¥{{ m.cache_input_price.toFixed(2) }}</p>
              <p v-else class="mt-0.5 text-sm text-stone-300">—</p>
            </div>
          </div>
          <div class="mt-3 text-xs text-stone-400">{{ brandOf(m) }}</div>
        </div>
      </div>
      <el-empty v-if="!filtered.length" description="没有匹配的模型" />
    </div>
    <SiteFooter />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import SiteNav from '../components/SiteNav.vue'
import SiteFooter from '../components/SiteFooter.vue'
import { getPublicModels } from '../api'
import { useUserStore } from '../stores/user'

const store = useUserStore()

// 厂商 = 模型品牌,从 display_name 前缀推导(vendor 存的是上游渠道商,不对外)
const BRANDS = [
  ['deepseek', 'DeepSeek'], ['glm', 'GLM 智谱'], ['kimi', 'Kimi 月之暗面'],
  ['minimax', 'MiniMax'], ['qwen', 'Qwen 通义'], ['ernie', '文心一言'],
  ['hunyuan', '腾讯混元'], ['doubao', '豆包'], ['grok', 'Grok'],
  ['claude', 'Claude'], ['gemini', 'Gemini'], ['llama', 'Llama'], ['mistral', 'Mistral'],
]
function brandOf(m) {
  const n = (m.display_name || m.name || '').toLowerCase()
  for (const [k, label] of BRANDS) {
    if (n.startsWith(k)) return label
  }
  const head = (m.display_name || m.name || '其他').split('-')[0]
  return head.charAt(0).toUpperCase() + head.slice(1)
}

function discountOf(m) {
  const rs = []
  if (m.official_input > 0) rs.push(m.input_price / m.official_input)
  if (m.official_output > 0) rs.push(m.output_price / m.official_output)
  if (!rs.length) return null
  return Math.round(Math.min(...rs) * 100) / 10 + ' 折'
}

const all = ref([])
const keyword = ref('')
const selectedVendors = ref([])

const vendors = computed(() => {
  const seen = new Map()
  for (const m of all.value) {
    const b = brandOf(m)
    seen.set(b, (seen.get(b) || 0) + 1)
  }
  return [...seen.keys()].sort((a, b) => seen.get(b) - seen.get(a) || a.localeCompare(b, 'zh'))
})

function vendorCount(v) {
  return all.value.filter((m) => brandOf(m) === v).length
}

// 多选:点击切换选中/取消;集合清空即回到「全部」
function toggleVendor(v) {
  const i = selectedVendors.value.indexOf(v)
  if (i >= 0) selectedVendors.value.splice(i, 1)
  else selectedVendors.value.push(v)
}
function clearVendor() {
  selectedVendors.value = []
}

const filtered = computed(() =>
  all.value.filter((m) => {
    if (selectedVendors.value.length && !selectedVendors.value.includes(brandOf(m))) return false
    const kw = keyword.value.trim().toLowerCase()
    return !kw || m.name.toLowerCase().includes(kw) || (m.display_name || '').toLowerCase().includes(kw)
  })
)

onMounted(async () => {
  const res = await getPublicModels()
  all.value = res.data || []
})
</script>
