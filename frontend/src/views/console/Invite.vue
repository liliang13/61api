<template>
  <div class="max-w-2xl">
    <h1 class="text-xl font-bold text-stone-800">邀请返佣</h1>
    <p class="mt-2 text-xs text-stone-400">把链接分享给朋友,TA 注册成功后你获得体验金奖励,上不封顶。</p>

    <div class="mt-6 rounded-2xl border border-black/5 bg-white p-6">
      <p class="text-xs text-stone-400">我的邀请链接</p>
      <div class="mt-2 flex gap-2">
        <el-input :model-value="invite?.invite_link" readonly size="large">
          <template #append>
            <el-button @click="copy">复制</el-button>
          </template>
        </el-input>
      </div>
      <p class="mt-2 text-xs text-stone-400">链接后缀为我的 UID:<code class="font-mono font-bold text-[#4f46e5]">{{ store.info?.uid }}</code> · 邀请码:<code class="font-mono font-bold text-[#4f46e5]">{{ invite?.invite_code }}</code>(旧链接仍有效)</p>
    </div>

    <div class="mt-5 grid grid-cols-2 gap-4">
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <p class="text-xs text-stone-400">已邀请用户</p>
        <p class="mt-2 text-2xl font-bold text-stone-800">{{ invite?.invited ?? 0 }}</p>
      </div>
      <div class="rounded-2xl border border-black/5 bg-white p-5">
        <p class="text-xs text-stone-400">累计奖励</p>
        <p class="mt-2 text-2xl font-bold text-[#4f46e5]">¥{{ invite?.total_yuan?.toFixed(2) ?? '0.00' }}</p>
      </div>
    </div>

    <h2 class="mt-8 font-bold text-stone-800">最近奖励</h2>
    <div class="mt-3 overflow-hidden rounded-2xl border border-black/5 bg-white">
      <el-table :data="invite?.recent || []" style="width: 100%" empty-text="暂无奖励记录">
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column label="新用户" width="140">
          <template #default="{ row }">用户 #{{ row.to_uid }}</template>
        </el-table-column>
        <el-table-column label="奖励" align="right">
          <template #default="{ row }"><span class="font-semibold text-[#4f46e5]">+¥{{ (row.quota / 500000).toFixed(2) }}</span></template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getInvite } from '../../api'
import { copyText } from '../../utils/clipboard'
import { useUserStore } from '../../stores/user'

const store = useUserStore()

const invite = ref(null)

async function copy() {
  await copyText(invite.value.invite_link, '邀请链接已复制')
}

onMounted(async () => { invite.value = (await getInvite()).data })
</script>
