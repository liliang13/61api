<template>
  <div class="hero-bg grid min-h-screen place-items-center px-4 pt-[64px]">
    <SiteNav />
    <div class="w-full max-w-[420px]">
      <div class="mb-6 text-center">
        <router-link to="/" class="inline-flex items-center gap-2">
          <img src="/logo-dark.png?v=3" alt="61API" class="h-10 w-10" />
          <span class="text-xl font-bold text-stone-800">61API</span>
        </router-link>
        <p class="mt-2 text-sm text-stone-500">{{ privateMode ? '私有化部署 · 企业 AI 网关' : '一个 API Key,聚合所有主流大模型' }}</p>
      </div>

      <div class="rounded-2xl border border-black/5 bg-white p-8 shadow-[0_8px_40px_rgba(0,0,0,0.06)]">
        <!-- 重置密码:整卡视图(由登录面板"忘记密码?"链接进入) -->
        <div v-if="tab === 'reset'" class="pt-1">
          <p class="mb-4 text-sm font-bold text-stone-800">重置密码</p>
          <el-form @submit.prevent="doReset">
            <el-form-item>
              <el-input v-model="resetForm.phone" placeholder="手机号" size="large" maxlength="11" />
            </el-form-item>
            <el-form-item>
              <div class="flex w-full gap-2">
                <el-input v-model="resetForm.code" placeholder="短信验证码" size="large" maxlength="6" />
                <el-button :disabled="countdown > 0" @click="sendCode('reset')" class="!px-3">
                  {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
                </el-button>
              </div>
            </el-form-item>
            <el-form-item>
              <el-input v-model="resetForm.password" type="password" placeholder="新密码(至少 10 位且含字母和数字)" size="large" show-password />
            </el-form-item>
            <div v-if="devCode" class="mb-3 rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
              开发模式:验证码为 <b>{{ devCode }}</b>
            </div>
            <el-button type="primary" size="large" class="w-full" :loading="loading" native-type="submit">重置密码</el-button>
            <div class="mt-3 text-xs text-stone-400">
              想起来了?<a class="cursor-pointer font-semibold text-[#4f46e5]" @click="tab = 'login'">返回登录</a>
            </div>
          </el-form>
        </div>

        <el-tabs v-else v-model="tab">
          <!-- 登录 -->
          <el-tab-pane label="登录" name="login">
            <el-radio-group v-if="!privateMode" v-model="loginMode" size="small" class="mb-4">
              <el-radio-button value="password">密码登录</el-radio-button>
              <el-radio-button value="sms">验证码登录</el-radio-button>
            </el-radio-group>

            <el-form @submit.prevent="doLogin">
              <el-form-item>
                <el-input v-model="loginForm.phone"
                  :placeholder="privateMode ? '用户名' : (loginMode === 'password' ? '手机号 / 用户名' : '手机号')"
                  size="large" :maxlength="loginMode === 'password' ? 32 : 11" />
              </el-form-item>

              <el-form-item v-if="loginMode === 'password'">
                <el-input v-model="loginForm.password" type="password" placeholder="密码" size="large" show-password />
              </el-form-item>

              <template v-else-if="!privateMode">
                <el-form-item>
                  <div class="flex w-full gap-2">
                    <el-input v-model="loginForm.code" placeholder="验证码" size="large" maxlength="6" />
                    <el-button :disabled="countdown > 0" @click="sendCode('login')" class="!px-3">
                      {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
                    </el-button>
                  </div>
                </el-form-item>
                <div v-if="devCode" class="mb-3 rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
                  开发模式:验证码为 <b>{{ devCode }}</b>(生产环境将通过短信发送)
                </div>
                <AliyunCaptcha ref="captcha" />
</template>

              <el-button type="primary" size="large" class="w-full" :loading="loading" native-type="submit">登 录</el-button>
              <div v-if="!privateMode" class="mt-3 flex justify-between text-xs text-stone-400">
                <span>没有账号?<a class="cursor-pointer font-semibold text-[#4f46e5]" @click="tab = 'register'">立即注册</a></span>
                <a v-if="loginMode === 'password'" class="cursor-pointer hover:text-[#4f46e5]" @click="tab = 'reset'">忘记密码?</a>
              </div>
              <p v-else class="mt-3 text-xs text-stone-400">账号由管理员统一开通,忘记密码请联系管理员重置。</p>
            </el-form>
          </el-tab-pane>

          <!-- 注册 -->
          <el-tab-pane v-if="!privateMode" label="注册" name="register">
            <el-form @submit.prevent="doRegister">
              <el-form-item>
                <el-input v-model="regForm.phone" placeholder="手机号" size="large" maxlength="11" />
              </el-form-item>
              <el-form-item>
                <div class="flex w-full gap-2">
                  <el-input v-model="regForm.code" placeholder="短信验证码" size="large" maxlength="6" />
                  <el-button :disabled="countdown > 0" @click="sendCode('register')" class="!px-3">
                    {{ countdown > 0 ? `${countdown}s` : '获取验证码' }}
                  </el-button>
                </div>
              </el-form-item>
              <el-form-item>
                <el-input v-model="regForm.password" type="password" placeholder="设置密码(至少 10 位且含字母和数字)" size="large" show-password />
              </el-form-item>
              <el-form-item>
                <el-input v-model="regForm.confirm" type="password" placeholder="确认密码" size="large" show-password />
              </el-form-item>
              <el-form-item>
                <el-input v-model="regForm.invite" placeholder="邀请码 / 邀请人 UID(选填)" size="large" />
              </el-form-item>
              <div v-if="devCode" class="mb-3 rounded-lg bg-[#f2f1fd] px-3 py-2 text-xs text-[#4f46e5]">
                开发模式:验证码为 <b>{{ devCode }}</b>
              </div>
              <el-button type="primary" size="large" class="w-full" :loading="loading" native-type="submit">注 册</el-button>
              <div class="mt-3 text-xs text-stone-400">
                已有账号?<a class="cursor-pointer font-semibold text-[#4f46e5]" @click="tab = 'login'">直接登录</a>
              </div>
            </el-form>
          </el-tab-pane>

        </el-tabs>
      </div>
      <p v-if="!privateMode" class="mt-4 text-center text-xs text-stone-400">登录即代表同意<a href="/terms" target="_blank" class="text-[#4f46e5] hover:underline">《服务条款》</a>与<a href="/privacy" target="_blank" class="text-[#4f46e5] hover:underline">《隐私政策》</a></p>
      <p v-else class="mt-4 text-center text-xs text-stone-400">企业内网使用 · 账号由管理员统一管理</p>
    </div>
  </div>
  <AliyunCaptcha v-if="siteLoaded && !privateMode" ref="captcha" />
</template>

<script setup>
import { computed, nextTick, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SiteNav from '../components/SiteNav.vue'
import { getSiteInfo, login, register, smsLogin, smsSendFor } from '../api'
import AliyunCaptcha from '../components/AliyunCaptcha.vue'
import http from '../api/http'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const tab = ref(route.query.mode === 'register' ? 'register' : 'login')
const loginMode = ref('password')
const loading = ref(false)
const countdown = ref(0)
const devCode = ref('')
const site = ref(null)
const siteLoaded = ref(false)
const privateMode = computed(() => !!site.value?.private)

const loginForm = ref({ phone: '', password: '', code: '' })
const regForm = ref({ phone: '', code: '', password: '', confirm: '', invite: route.query.invite || '' })
const resetForm = ref({ phone: '', code: '', password: '' })
const captcha = ref(null)

async function finish(data) {
  store.info = data.user
  store.restored = true
  ElMessage.success('欢迎回来!')
  router.push(route.query.redirect || '/console/dashboard')
}

onMounted(async () => {
  try {
    site.value = (await getSiteInfo()).data
  } catch { /* 站点信息失败不影响登录 */ }
  siteLoaded.value = true
  if (privateMode.value) {
    tab.value = 'login'
    loginMode.value = 'password'
  }
  // 私有化模式不加载阿里云人机验证 SDK,避免离线环境发起外部请求
  await nextTick()
  if (privateMode.value) return
  captcha.value?.attach(async (phone, purpose, cvp) => {
    try {
      const res = await smsSendFor(phone, purpose, cvp)
      if (res.data?.dev_code) devCode.value = res.data.dev_code
      ElMessage.success('验证码已发送')
      return { captchaResult: true, bizResult: true }
    } catch (e) {
      // 428=阿里云验签未通过;其余(未注册/已注册/频控)为业务失败,验签本身已通过
      const st = e.response?.status
      return { captchaResult: st !== 428, bizResult: false }
    }
  })
})

function startCountdown() {
  countdown.value = 60
  const timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) clearInterval(timer)
  }, 1000)
}

async function sendCode(purpose) {
  const phone = purpose === 'register' ? regForm.value.phone
    : purpose === 'reset' ? resetForm.value.phone : loginForm.value.phone
  if (!/^1[3-9]\d{9}$/.test(phone)) return ElMessage.warning('请填写正确的手机号')
  // 触发阿里云人机验证;滑块通过后 SDK 自动回调完成 验签+发码(见组件 attach)
  await captcha.value.request(phone, purpose, { onDone: startCountdown })
}

async function doLogin() {
  const f = loginForm.value
  const id = f.phone.trim()
  const isPhone = /^1[3-9]\d{9}$/.test(id)
  const isName = /^[A-Za-z0-9_]{3,32}$/.test(id)
  if (!isPhone && !isName) return ElMessage.warning('请输入正确的手机号或用户名')
  loading.value = true
  try {
    if (loginMode.value === 'password') {
      if (!f.password) return ElMessage.warning('请填写密码')
      await finish((await login({ phone: id, password: f.password })).data)
    } else {
      if (!isPhone) return ElMessage.warning('验证码登录请使用手机号')
      if (!f.code) return ElMessage.warning('请填写验证码')
      await finish((await smsLogin({ phone: id, code: f.code })).data)
    }
  } finally { loading.value = false }
}

async function doRegister() {
  const f = regForm.value
  if (!/^1[3-9]\d{9}$/.test(f.phone)) return ElMessage.warning('请填写正确的手机号')
  if (!f.code) return ElMessage.warning('请填写短信验证码')
  if (f.password.length < 10 || !/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) return ElMessage.warning('密码至少 10 位且包含字母和数字')
  if (f.password !== f.confirm) return ElMessage.warning('两次输入的密码不一致')
  loading.value = true
  try {
    await finish((await register({ phone: f.phone, code: f.code, password: f.password, invite_code: f.invite })).data)
  } finally { loading.value = false }
}

async function doReset() {
  const f = resetForm.value
  if (!/^1[3-9]\d{9}$/.test(f.phone)) return ElMessage.warning('请填写正确的手机号')
  if (!f.code) return ElMessage.warning('请填写短信验证码')
  if (f.password.length < 10 || !/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) return ElMessage.warning('密码至少 10 位且包含字母和数字')
  loading.value = true
  try {
    await http.post('/auth/password/reset', { phone: f.phone, code: f.code, new_password: f.password })
    ElMessage.success('密码已重置,请登录')
    tab.value = 'login'
    loginMode.value = 'password'
    loginForm.value.phone = f.phone
  } finally { loading.value = false }
}
</script>
