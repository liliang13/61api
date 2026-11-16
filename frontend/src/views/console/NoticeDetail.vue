<template>
  <div class="max-w-2xl">
    <el-button link class="!px-0" @click="$router.push('/console/notices')">
      ← 返回消息中心
    </el-button>
    <div v-if="notice" class="mt-4 rounded-2xl border border-black/5 bg-white p-6">
      <h1 class="text-xl font-bold text-stone-800">{{ notice.title }}</h1>
      <p class="mt-2 text-xs text-stone-400">发布时间:{{ notice.created_at }}</p>
      <div class="mt-5 whitespace-pre-wrap text-sm leading-7 text-stone-600">{{ notice.body }}</div>
    </div>
    <el-skeleton v-else-if="loading" class="mt-4" :rows="6" animated />
    <el-empty v-else description="消息不存在或已下架" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getNoticeDetail } from '../../api'

const route = useRoute()
const notice = ref(null)
const loading = ref(true)

onMounted(async () => {
  try {
    // 打开详情即标记已读(后端行为)
    notice.value = (await getNoticeDetail(route.params.id)).data
  } catch {
    notice.value = null
  } finally {
    loading.value = false
  }
})
</script>
