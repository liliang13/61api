<template>
  <div class="max-w-3xl">
    <el-button link class="!px-0" @click="$router.push('/console/tickets')">← 返回工单列表</el-button>

    <div v-if="ticket" class="mt-4">
      <div class="rounded-2xl border border-black/5 bg-white p-6">
        <div class="flex items-start justify-between gap-3">
          <h1 class="text-lg font-bold text-stone-800">{{ ticket.title }}</h1>
          <el-tag size="small" effect="plain" :type="statusType(ticket.status)">{{ statusText(ticket.status) }}</el-tag>
        </div>
        <p class="mt-1 text-xs text-stone-400">工单号 #{{ ticket.id }} · 创建于 {{ ticket.created_at }}</p>
      </div>

      <!-- 对话 -->
      <div class="mt-4 space-y-3">
        <div v-for="m in ticket.messages" :key="m.id"
          class="rounded-2xl border p-4"
          :class="m.sender_role === 'admin' ? 'border-[#4f46e5]/20 bg-[#eef2ff]/60' : 'border-black/5 bg-white'">
          <div class="mb-1.5 flex items-center justify-between text-xs">
            <span class="font-semibold" :class="m.sender_role === 'admin' ? 'text-[#4f46e5]' : 'text-stone-500'">
              {{ m.sender_role === 'admin' ? '官方客服' : '我' }}
            </span>
            <span class="text-stone-400">{{ m.created_at }}</span>
          </div>
          <p class="whitespace-pre-wrap text-sm leading-6 text-stone-700">{{ m.content }}</p>
          <el-image v-if="m.file_key" :src="`/api/user/tickets/${ticket.id}/messages/${m.id}/file`"
            :preview-src-list="[`/api/user/tickets/${ticket.id}/messages/${m.id}/file`]"
            fit="cover" class="mt-2 w-40 rounded-lg border border-black/5" preview-teleported />
        </div>
      </div>

      <!-- 回复 -->
      <div v-if="ticket.status !== 'closed'" class="mt-4 rounded-2xl border border-black/5 bg-white p-4">
        <el-input v-model="reply" type="textarea" :rows="4" maxlength="5000" show-word-limit
          placeholder="补充说明或追问…" />
        <div class="mt-2 flex items-center gap-2">
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif"
            @change="onFileChange" class="block text-sm text-stone-600
            file:mr-3 file:rounded-lg file:border-0 file:bg-[#eef2ff] file:px-3 file:py-1.5
            file:text-xs file:font-semibold file:text-[#4f46e5] hover:file:bg-[#e0e7ff]" />
          <span v-if="replyFile" class="text-xs text-stone-500">{{ replyFile.name }}</span>
          <el-button v-if="replyFile" link type="danger" size="small" @click="replyFile = null">移除</el-button>
        </div>
        <div class="mt-3 flex justify-between">
          <el-button link type="danger" @click="doClose">关闭工单</el-button>
          <el-button type="primary" :loading="replying" @click="doReply">发送回复</el-button>
        </div>
      </div>
      <div v-else class="mt-4 rounded-2xl border border-black/5 bg-[#fafafa] p-4 text-center text-sm text-stone-400">
        工单已关闭。如仍有问题,请返回列表提交新工单。
      </div>
    </div>
    <el-skeleton v-else-if="loading" class="mt-4" :rows="6" animated />
    <el-empty v-else description="工单不存在" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTicket, replyTicket, closeTicket, uploadTicketAttachment } from '../../api'

const route = useRoute()
const ticket = ref(null)
const reply = ref('')
const replyFile = ref(null)
const replying = ref(false)
const loading = ref(true)

function statusText(s) {
  return { open: '待处理', answered: '已回复', closed: '已关闭' }[s] || s
}
function statusType(s) {
  return { open: 'warning', answered: 'success', closed: 'info' }[s] || 'info'
}

async function load() {
  try {
    ticket.value = (await getTicket(route.params.id)).data
  } catch {
    ticket.value = null
  } finally {
    loading.value = false
  }
}

function onFileChange(e) {
  const f = e.target.files[0] || null
  if (!f) { replyFile.value = null; return }
  if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(f.type)) {
    e.target.value = ''
    ElMessage.warning('仅支持 PNG/JPG/WebP/GIF 图片')
    return
  }
  if (f.size > 5 * 1024 * 1024) {
    e.target.value = ''
    ElMessage.warning('图片大小不能超过 5MB')
    return
  }
  replyFile.value = f
}

async function doReply() {
  if (!reply.value.trim()) return ElMessage.warning('请输入回复内容')
  replying.value = true
  try {
    let attachment
    if (replyFile.value) {
      try {
        attachment = (await uploadTicketAttachment(replyFile.value)).data
      } catch (e) {
        return ElMessage.error(e.response?.data?.error || '附件上传失败')
      }
    }
    await replyTicket(route.params.id, {
      content: reply.value.trim(),
      attachment: attachment ? { key: attachment.key, name: attachment.name, size: attachment.size } : undefined,
    })
    reply.value = ''
    replyFile.value = null
    await load()
  } finally { replying.value = false }
}

async function doClose() {
  await closeTicket(route.params.id)
  ElMessage.success('工单已关闭')
  await load()
}

onMounted(load)
</script>
