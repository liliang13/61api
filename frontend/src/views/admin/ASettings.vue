<template>
  <div>
    <h1 class="text-xl font-bold text-stone-800">站点设置</h1>
    <div class="mt-5 max-w-2xl rounded-2xl border border-black/5 bg-white p-6" v-if="form">
      <el-form label-position="top">
        <el-form-item label="站点名称"><el-input v-model="form.site_name" /></el-form-item>
        <el-form-item label="站内公告(控制台顶部横幅)">
          <el-input v-model="form.announcement" type="textarea" :rows="3" placeholder="留空则不展示公告" />
        </el-form-item>
        <div class="grid grid-cols-2 gap-4">
          <el-form-item label="公告链接(选填,「查看详情」跳转)">
            <el-input v-model="form.announcement_link" placeholder="https://..." />
          </el-form-item>
          <el-form-item label="显示公告">
            <el-switch v-model="form.announcement_enabled" />
          </el-form-item>
        </div>
        <div v-if="!store.isPrivate" class="grid grid-cols-2 gap-4">
          <el-form-item label="首页折扣文案(0.5 = 5 折)">
            <el-input-number v-model="form.discount_note" :min="0.1" :max="1" :precision="2" :step="0.1" class="!w-full" />
            <p class="mt-1 text-xs text-stone-400">填写后首页"X 折 起"固定显示该值;留空则按模型目录相对官方原价自动取最低折扣。</p>
          </el-form-item>
          <el-form-item label="新用户注册赠送(元)"><el-input-number v-model="form.new_user_bonus_cny" :min="0" :precision="2" :step="0.5" class="!w-full" /></el-form-item>
          <el-form-item label="邀请奖励(元/人)"><el-input-number v-model="form.invite_bonus_cny" :min="0" :precision="2" :step="0.5" class="!w-full" /></el-form-item>
          <el-form-item label="允许自定义金额充值"><el-switch v-model="form.custom_topup_enabled" /></el-form-item>
          <el-form-item label="客服二维码图片 URL(控制台左下角「联系客服」展示)">
            <el-input v-model="form.kefu_qr_url" placeholder="https://…(企业微信二维码图片地址,留空显示邮箱兜底)" />
          </el-form-item>
          <el-form-item label="自定义充值最低(元)"><el-input-number v-model="form.custom_topup_min_yuan" :min="0.01" :precision="2" :step="1" class="!w-full" /></el-form-item>
          <el-form-item label="自定义充值最高(元)"><el-input-number v-model="form.custom_topup_max_yuan" :min="0.01" :precision="2" :step="100" class="!w-full" /></el-form-item>
        </div>
      </el-form>
      <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
    </div>

    <div v-if="store.feature('payments')" class="mt-5 rounded-2xl border border-black/5 bg-white p-6">
      <div class="flex items-center justify-between">
        <h2 class="font-bold text-stone-800">充值套餐</h2>
        <el-button size="small" @click="addPkg">+ 新增套餐</el-button>
      </div>
      <p class="mt-1 text-xs text-stone-400">到账额度 = 充值金额 ×(1 + 赠送比例)。列表顺序即控制台展示顺序,可用上移/下移调整;套餐 ID 可改,保存后生效。</p>
      <el-table :data="packages" class="mt-3" size="default">
        <el-table-column label="套餐 ID" width="130">
          <template #default="{ row }"><el-input v-model="row.id" size="small" placeholder="字母/数字/-/_" /></template>
        </el-table-column>
        <el-table-column label="名称" min-width="140">
          <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
        </el-table-column>
        <el-table-column label="金额(元)" width="140" align="center">
          <template #default="{ row }">
            <el-input-number v-model="row.yuan" :min="0.01" :precision="2" :step="10" size="small" class="!w-28" />
          </template>
        </el-table-column>
        <el-table-column label="赠送比例(%)" width="150" align="center">
          <template #default="{ row }">
            <el-input-number v-model="row.bonus_pct" :min="0" :max="100" :precision="0" :step="5" size="small" class="!w-28" />
          </template>
        </el-table-column>
        <el-table-column label="到账预览" width="120" align="right">
          <template #default="{ row }">¥{{ ((row.yuan * (1 + (row.bonus_pct || 0) / 100)) || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="排序" width="110" align="center">
          <template #default="{ $index }">
            <el-button link size="small" :disabled="$index === 0" @click="movePackage($index, -1)">上移</el-button>
            <el-button link size="small" :disabled="$index === packages.length - 1" @click="movePackage($index, 1)">下移</el-button>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ $index }">
            <el-button link type="danger" size="small" @click="packages.splice($index, 1)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button class="mt-3" type="primary" :loading="savingPkg" @click="savePackages">保存套餐</el-button>
    </div>

    <div class="mt-5 max-w-2xl rounded-2xl border border-black/5 bg-white p-6">
      <h2 class="font-bold text-stone-800">渠道探活与异常通知</h2>
      <p class="mt-1 text-xs text-stone-400">
        定时探活由服务器上的 systemd timer 调用(deploy/61api-probe.timer,每 5 分钟)。渠道连续探活失败达到阈值会自动禁用并推送通知;
        被自动禁用的渠道连续 2 次探活成功后自动恢复上线。通知只在禁用/恢复两个时刻推送。
      </p>
      <el-form label-position="top" class="mt-3">
        <div class="grid grid-cols-2 gap-4">
          <el-form-item label="探活失败自动禁用(阈值次数)">
            <el-input-number v-model="form.probe_disable_threshold" :min="1" :max="10" :precision="0" :step="1" class="!w-full" />
          </el-form-item>
          <el-form-item label="开启异常通知">
            <el-switch v-model="form.notify_enabled" />
          </el-form-item>
          <el-form-item label="通知机器人类型">
            <el-select v-model="form.notify_webhook_type" class="w-full">
              <el-option label="企业微信群机器人" value="wecom" />
              <el-option label="钉钉群机器人" value="dingtalk" />
              <el-option label="飞书群机器人" value="feishu" />
            </el-select>
          </el-form-item>
          <el-form-item label="机器人 Webhook 地址">
            <el-input v-model="form.notify_webhook_url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" />
          </el-form-item>
        </div>
      </el-form>
      <div class="flex gap-2">
        <el-button type="primary" :loading="savingNotify" @click="saveNotify">保存通知设置</el-button>
        <el-button :loading="testingNotify" @click="testNotify">发送测试通知</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminGetSettings, adminNotifyTest, adminPutSettings } from '../../api'
import { createPackageId, validatePackages } from '../../utils/packages'
import { useUserStore } from '../../stores/user'

const store = useUserStore()

const form = ref(null)
const saving = ref(false)
const savingPkg = ref(false)
const savingNotify = ref(false)
const testingNotify = ref(false)

const packages = ref([])

function syncPackagesFromForm() {
  packages.value = (form.value?.topup_packages ?? []).map((p) => ({
    id: p.id, name: p.name, yuan: (p.price || 0) / 100, bonus_pct: p.bonus_pct || 0,
  }))
}

function addPkg() {
  packages.value.push({ id: createPackageId(packages.value), name: '新套餐', yuan: 10, bonus_pct: 0 })
}

function movePackage(index, delta) {
  const target = index + delta
  if (target < 0 || target >= packages.value.length) return
  const [row] = packages.value.splice(index, 1)
  packages.value.splice(target, 0, row)
}

async function save() {
  saving.value = true
  try {
    await adminPutSettings({
      site_name: form.value.site_name,
      announcement: form.value.announcement,
      announcement_link: form.value.announcement_link,
      announcement_enabled: form.value.announcement_enabled,
      discount_note: form.value.discount_note,
      new_user_bonus_cny: form.value.new_user_bonus_cny,
      invite_bonus_cny: form.value.invite_bonus_cny,
      custom_topup_enabled: form.value.custom_topup_enabled,
      custom_topup_min_yuan: form.value.custom_topup_min_yuan,
      custom_topup_max_yuan: form.value.custom_topup_max_yuan,
    })
    ElMessage.success('设置已保存')
  } finally { saving.value = false }
}

async function savePackages() {
  const validationError = validatePackages(packages.value)
  if (validationError) return ElMessage.warning(validationError)
  savingPkg.value = true
  try {
    await adminPutSettings({ topup_packages: packages.value.map((p) => ({
      id: String(p.id).trim(), name: String(p.name).trim(), price: Math.round(p.yuan * 100), bonus_pct: p.bonus_pct,
    })) })
    ElMessage.success('套餐已保存,刷新页面后收银台生效')
  } finally { savingPkg.value = false }
}

async function saveNotify() {
  savingNotify.value = true
  try {
    await adminPutSettings({
      probe_disable_threshold: form.value.probe_disable_threshold,
      notify_enabled: form.value.notify_enabled,
      notify_webhook_type: form.value.notify_webhook_type,
      notify_webhook_url: String(form.value.notify_webhook_url || '').trim(),
    })
    ElMessage.success('通知设置已保存')
  } finally { savingNotify.value = false }
}

async function testNotify() {
  testingNotify.value = true
  try { await adminNotifyTest() } finally { testingNotify.value = false }
}

onMounted(async () => { form.value = (await adminGetSettings()).data
  form.value.announcement_link = form.value.announcement_link || ''
  form.value.announcement_enabled = form.value.announcement_enabled !== false
  form.value.custom_topup_min_yuan = form.value.custom_topup_min_yuan ?? 1
  form.value.custom_topup_max_yuan = form.value.custom_topup_max_yuan ?? 5000
  form.value.custom_topup_enabled = form.value.custom_topup_enabled !== false
  form.value.probe_disable_threshold = form.value.probe_disable_threshold ?? 3
  form.value.notify_enabled = form.value.notify_enabled === true
  form.value.notify_webhook_type = form.value.notify_webhook_type || 'wecom'
  form.value.notify_webhook_url = form.value.notify_webhook_url || ''
  syncPackagesFromForm() })
</script>
