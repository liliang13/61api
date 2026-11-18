<template>
  <div class="max-w-xl space-y-6">
    <h1 class="text-xl font-bold text-stone-800">账户设置</h1>

    <!-- 基本信息 -->
    <div class="rounded-2xl border border-black/5 bg-white p-6">
      <h2 class="font-bold text-stone-800">基本信息</h2>
      <div class="mt-4 space-y-2 text-sm text-stone-600">
        <p>UID:<code class="rounded bg-black/5 px-1.5 font-mono font-bold text-[#4f46e5]">{{ store.info?.uid || "-" }}</code></p>
        <p>用户名:<b>{{ store.info?.username }}</b><el-tag v-if="store.isAdmin" size="small" type="warning" class="ml-2">管理员</el-tag></p>
        <p>手机号:{{ maskedPhone || '未绑定' }}</p>
        <p>注册时间:{{ store.info?.created_at }}</p>
      </div>
    </div>

    <!-- 绑定/更换手机(短信启用时显示) -->
    <div v-if="store.feature('sms')" class="rounded-2xl border border-black/5 bg-white p-6">
      <h2 class="font-bold text-stone-800">{{ hasPhone ? '更换手机号' : '绑定手机号' }}</h2>

      <!-- 第一步:验证当前手机号 -->
      <div v-if="hasPhone && step === 1" class="mt-4 space-y-3">
        <p class="text-xs text-stone-400">为保障账号安全,请先验证当前绑定的手机号 {{ maskedPhone }}</p>
        <div class="flex gap-2">
          <el-input v-model="oldCode" placeholder="当前手机号短信验证码" maxlength="6" />
          <el-button :disabled="oldCountdown > 0" @click="sendOldCode" class="!w-32">
            {{ oldCountdown > 0 ? `${oldCountdown}s` : '获取验证码' }}
          </el-button>
        </div>
        <div v-if="oldDevCode" class="rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
          开发模式:验证码为 <b>{{ oldDevCode }}</b>
        </div>
        <el-button type="primary" :loading="verifyingOld" @click="verifyOld">验证当前手机号</el-button>
      </div>

      <!-- 第二步:绑定新手机号 -->
      <div v-if="step === 2" class="mt-4 space-y-3">
        <div v-if="hasPhone" class="flex items-center justify-between rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
          <span>当前手机号已验证,请输入新手机号</span>
          <el-button link type="primary" @click="backToStep1">重新验证</el-button>
        </div>
        <el-input v-model="phone" placeholder="新手机号" maxlength="11" />
        <div class="flex gap-2">
          <el-input v-model="smsCode" placeholder="新手机号短信验证码" maxlength="6" />
          <el-button :disabled="countdown > 0" @click="sendBindCode" class="!w-32">
            {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
          </el-button>
        </div>
        <div v-if="devCode" class="rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
          开发模式:验证码为 <b>{{ devCode }}</b>
        </div>
        <el-button type="primary" @click="doBind">确认绑定</el-button>
      </div>
    </div>

    <!-- 修改密码 -->
    <div class="rounded-2xl border border-black/5 bg-white p-6">
      <h2 class="font-bold text-stone-800">修改密码</h2>
      <div class="mt-4 space-y-3">
        <el-input v-model="pwd.old_password" type="password" placeholder="原密码(首次设置可留空)" show-password />
        <el-input v-model="pwd.new_password" type="password" placeholder="新密码(至少 10 位且含字母和数字)" show-password />
        <el-input v-model="pwd.confirm" type="password" placeholder="确认新密码" show-password />
        <el-button type="primary" @click="doChangePwd">保存新密码</el-button>
      </div>
    </div>

    <!-- 注销账户 -->
    <div class="rounded-2xl border border-red-100 bg-white p-6">
      <h2 class="font-bold text-red-600">危险区</h2>
      <div class="mt-3 space-y-3 text-sm text-stone-600">
        <p>注销后账户立即停用,所有 API 密钥失效,当前手机号将被释放,可重新注册新账户。历史订单与用量数据将依法保留。</p>
        <el-button type="danger" plain @click="delVisible = true">注销账户</el-button>
      </div>
    </div>

    <el-dialog v-model="delVisible" title="确认注销账户" width="420px">
      <div class="space-y-3 text-sm text-stone-600">
        <p>此操作<b class="text-red-600">不可恢复</b>:账户余额与资源包将无法再使用,请确认已无需保留。</p>
        <el-input v-model="delPassword" type="password" placeholder="请输入账户密码确认" show-password @keydown.enter="doDelete" />
      </div>
      <template #footer>
        <el-button @click="delVisible = false">取消</el-button>
        <el-button type="danger" :loading="deleting" @click="doDelete">确认注销</el-button>
      </template>
    </el-dialog>
  </div>
  <AliyunCaptcha ref="captcha" />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import {
  bindPhone, bindPhoneSend, changePassword, changePhoneSendOld,
  changePhoneVerifyOld, deleteAccount,
} from '../../api'
import AliyunCaptcha from '../../components/AliyunCaptcha.vue'
import { useUserStore } from '../../stores/user'

const store = useUserStore()
const router = useRouter()
const step = ref(1)
const phone = ref('')
const smsCode = ref('')
const devCode = ref('')
const countdown = ref(0)
const oldCode = ref('')
const oldDevCode = ref('')
const oldCountdown = ref(0)
const verifyingOld = ref(false)
const ticket = ref('')
const captcha = ref(null)
const pwd = ref({ old_password: '', new_password: '', confirm: '' })
let countdownTimer = null
let oldTimer = null

const hasPhone = computed(() => !!store.info?.phone)
const maskedPhone = computed(() => {
  const p = store.info?.phone || ''
  return p.length === 11 ? `${p.slice(0, 3)}****${p.slice(7)}` : p
})

function startCountdown() {
  clearInterval(countdownTimer)
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) clearInterval(countdownTimer)
  }, 1000)
}

function startOldCountdown() {
  clearInterval(oldTimer)
  oldCountdown.value = 60
  oldTimer = setInterval(() => {
    oldCountdown.value -= 1
    if (oldCountdown.value <= 0) clearInterval(oldTimer)
  }, 1000)
}

onMounted(() => {
  step.value = hasPhone.value ? 1 : 2
  // 第二步(向新手机号发码)保留人机验证;票据由第一步签发
  captcha.value?.attach(async (p, _purpose, cvp) => {
    try {
      const res = await bindPhoneSend(p, cvp, hasPhone.value ? ticket.value : undefined)
      if (res.data?.dev_code) devCode.value = res.data.dev_code
      ElMessage.success('验证码已发送')
      return { captchaResult: true, bizResult: true }
    } catch (e) {
      // 票据过期等原因(428)回到第一步重新验证
      if (e.response?.status === 428 && hasPhone.value && String(e.response?.data?.error || '').includes('当前手机号')) {
        step.value = 1
        ticket.value = ''
      }
      return { captchaResult: e.response?.status !== 428, bizResult: false }
    }
  })
})

onUnmounted(() => { clearInterval(countdownTimer); clearInterval(oldTimer) })

async function sendOldCode() {
  try {
    const res = await changePhoneSendOld()
    if (res.data?.dev_code) oldDevCode.value = res.data.dev_code
    ElMessage.success('验证码已发送至当前手机号')
    startOldCountdown()
  } catch { /* 错误提示由 http 拦截器统一处理 */ }
}

async function verifyOld() {
  if (!/^\d{4,6}$/.test(oldCode.value)) return ElMessage.warning('请输入收到的验证码')
  verifyingOld.value = true
  try {
    const res = await changePhoneVerifyOld(oldCode.value)
    ticket.value = res.data?.ticket || ''
    step.value = 2
    phone.value = ''
    smsCode.value = ''
    devCode.value = ''
    ElMessage.success('当前手机号验证通过')
  } finally { verifyingOld.value = false }
}

function backToStep1() {
  step.value = 1
  ticket.value = ''
  oldCode.value = ''
}

async function sendBindCode() {
  if (!/^1[3-9]\d{9}$/.test(phone.value)) return ElMessage.warning('请填写正确的新手机号')
  if (hasPhone.value && !ticket.value) {
    step.value = 1
    return ElMessage.warning('请先验证当前手机号')
  }
  await captcha.value?.request(phone.value, 'bind', { onDone: startCountdown })
}

async function doBind() {
  if (!/^1[3-9]\d{9}$/.test(phone.value)) return ElMessage.warning('请填写正确的新手机号')
  await bindPhone({
    phone: phone.value, code: smsCode.value,
    ticket: hasPhone.value ? ticket.value : undefined,
  })
  ElMessage.success(hasPhone.value ? '手机号更换成功' : '绑定成功')
  ticket.value = ''
  await store.fetchMe()
  step.value = 1
}

async function doChangePwd() {
  const password = pwd.value.new_password
  if (password.length < 10 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) return ElMessage.warning('密码至少 10 位且包含字母和数字')
  if (password !== pwd.value.confirm) return ElMessage.warning('两次输入的新密码不一致')
  await changePassword({ old_password: pwd.value.old_password, new_password: pwd.value.new_password })
  ElMessage.success('密码已更新')
  pwd.value = { old_password: '', new_password: '', confirm: '' }
}

const delVisible = ref(false)
const delPassword = ref('')
const deleting = ref(false)

async function doDelete() {
  if (!delPassword.value) return ElMessage.warning('请输入账户密码确认')
  deleting.value = true
  try {
    await deleteAccount({ password: delPassword.value })
    delVisible.value = false
    ElMessage.success('账户已注销')
    await store.logout()
    router.push('/')
  } finally {
    deleting.value = false
    delPassword.value = ''
  }
}
</script>
