<template>
  <div>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-bold text-stone-800">消息中心</h1>
      <el-button :disabled="!hasUnread" @click="readAll">全部已读</el-button>
    </div>
    <p class="mt-2 text-xs text-stone-400">平台公告与通知 · 点击消息查看详情</p>

    <div class="mt-5 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <div v-if="items.length" class="divide-y divide-black/5">
        <div v-for="i in items" :key="i.id" @click="$router.push(`/console/notices/${i.id}`)"
          class="flex cursor-pointer items-center gap-3 px-5 py-4 transition-colors hover:bg-[#fafafa]">
          <span v-if="!i.read" class="h-2 w-2 shrink-0 rounded-full bg-[#ef4444]"></span>
          <span v-else class="w-2 shrink-0"></span>
          <span class="min-w-0 flex-1 truncate text-sm"
            :class="i.read ? 'text-stone-500' : 'font-semibold text-stone-800'">{{ i.title }}</span>
          <span class="shrink-0 text-xs text-stone-400">{{ i.created_at }}</span>
        </div>
      </div>
      <el-empty v-else description="暂无消息" />
    </div>
    <div class="mt-5 flex justify-center">
      <el-pagination layout="prev, pager, next, total" :total="total" :page-size="size"
        v-model:current-page="page" @current-change="load" hide-on-single-page />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getMyNotices, readAllNotices } from '../../api'

const items = ref([])
const total = ref(0)
const page = ref(1)
const size = 15

const hasUnread = computed(() => items.value.some((i) => !i.read))

async function load() {
  const res = await getMyNotices({ page: page.value, page_size: size })
  items.value = res.data?.items || []
  total.value = res.data?.total || 0
}

async function readAll() {
  await readAllNotices()
  ElMessage.success('已全部标记为已读')
  await load()
}

onMounted(load)
</script>
