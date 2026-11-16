<template>
  <el-popover placement="bottom-end" :width="340" trigger="click" @show="loadList">
    <template #reference>
      <button class="relative grid h-9 w-9 place-items-center rounded-lg text-stone-500 transition-colors hover:bg-[#f5f5f5] hover:text-[#4f46e5]"
        title="消息通知" aria-label="消息通知">
        <Bell class="h-5 w-5" />
        <span v-if="unread > 0"
          class="absolute -right-0.5 -top-0.5 grid min-w-[18px] place-items-center rounded-full bg-[#ef4444] px-1 text-[10px] font-bold leading-[18px] text-white">
          {{ unread > 99 ? '99+' : unread }}
        </span>
      </button>
    </template>
    <div>
      <div class="mb-2 flex items-center justify-between">
        <span class="text-sm font-bold text-stone-800">消息通知</span>
        <el-button link type="primary" size="small" :disabled="!unread" @click="readAll">全部已读</el-button>
      </div>
      <div v-if="items.length" class="-mx-2 max-h-80 overflow-y-auto">
        <div v-for="i in items" :key="i.id" @click="openDetail(i)"
          class="cursor-pointer rounded-lg px-2 py-2 transition-colors hover:bg-[#f5f5f5]">
          <div class="flex items-center gap-2">
            <span v-if="!i.read" class="h-1.5 w-1.5 shrink-0 rounded-full bg-[#ef4444]"></span>
            <span class="min-w-0 flex-1 truncate text-sm"
              :class="i.read ? 'text-stone-500' : 'font-semibold text-stone-800'">{{ i.title }}</span>
          </div>
          <p class="mt-0.5 pl-3.5 text-xs text-stone-400">{{ i.created_at }}</p>
        </div>
      </div>
      <el-empty v-else description="暂无消息" :image-size="60" />
      <div class="mt-1 border-t border-black/5 pt-2 text-center">
        <router-link to="/console/notices" class="text-xs font-semibold text-[#4f46e5] hover:underline"
          @click="emit('close')">查看全部消息</router-link>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { getMyNotices, getNoticeUnread, readAllNotices } from '../api'

const emit = defineEmits(['close'])
const router = useRouter()
const route = useRoute()
const unread = ref(0)
const items = ref([])
let timer = null

async function refreshUnread() {
  try {
    unread.value = (await getNoticeUnread()).data?.unread || 0
  } catch { /* 未登录等场景静默 */ }
}

async function loadList() {
  try {
    items.value = (await getMyNotices({ page: 1, page_size: 8 })).data?.items || []
  } catch { /* 静默 */ }
}

async function readAll() {
  await readAllNotices()
  ElMessage.success('已全部标记为已读')
  await Promise.all([refreshUnread(), loadList()])
}

function openDetail(i) {
  emit('close')
  router.push(`/console/notices/${i.id}`)
}

// 详情页打开后端即标记已读,导航完成立即刷新未读数(不等 60s 轮询)
watch(() => route.fullPath, () => { refreshUnread() })

onMounted(() => {
  refreshUnread()
  loadList()
  timer = setInterval(refreshUnread, 60000)
})
onUnmounted(() => { clearInterval(timer) })

defineExpose({ refreshUnread })
</script>
