<template>
  <div>
    <div id="aliyun-captcha-element"></div>
    <button ref="trigger" id="aliyun-captcha-trigger" type="button" aria-hidden="true"
      style="position:fixed;left:0;bottom:0;width:8px;height:8px;opacity:0;pointer-events:none;border:0;background:none;"></button>
  </div>
</template>

<script setup>
// 阿里云验证码 2.0(V2 架构,无痕验证形态)。
// 官方要点:
//  - AliyunCaptchaConfig 必须在 JS 引入之前设置;
//  - JS 加载与验证请求间隔需 >2s(设备环境采集),因此页面挂载即预初始化,
//    用户点击"获取验证码"时 SDK 已就绪;
//  - 无痕验证:点击 button → SDK 静默风险判定 → 低风险直接调 captchaVerifyCallback
//    (在回调内完成 后端验签+发码,返回 {captchaResult, bizResult});
//    高风险时 SDK 自动降级滑块二次验证,仍走同一回调。
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

const SCENE_ID = '1lfqb6sd'
const PREFIX = 'tzznjx'
const JS_URL = 'https://o.alicdn.com/captcha-frontend/aliyunCaptcha/AliyunCaptcha.js'

const trigger = ref(null)
let instance = null

window.AliyunCaptchaConfig = { region: 'cn', prefix: PREFIX }

let ready = null
// 状态挂 window:SDK 回调可能来自任意一份组件实例作用域,必须全局共享
window.__mgCap = window.__mgCap || { currentPhone: '', currentPurpose: 'login', sendFn: null, onDoneFn: null }
const st = () => window.__mgCap

function loadScript() {
  if (window.initAliyunCaptcha) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = JS_URL
    s.onload = resolve
    s.onerror = () => reject(new Error('load fail'))
    document.head.appendChild(s)
  })
}

function init() {
  if (ready) return ready
  ready = loadScript().then(() => {
    window.initAliyunCaptcha({
      SceneId: SCENE_ID,
      mode: 'popup',
      element: '#aliyun-captcha-element',
      button: '#aliyun-captcha-trigger',
      slideStyle: { width: 320, height: 40 },
      language: 'cn',
      getInstance(i) { instance = i; window.__aliyunCaptchaInstance = i },
      async captchaVerifyCallback(captchaVerifyParam) {
        const S = st()
        if (!S.sendFn) return { captchaResult: true }
        try {
          return await S.sendFn(S.currentPhone, S.currentPurpose, captchaVerifyParam)
        } catch {
          ElMessage.error('验证码请求失败,请稍后重试')
          return { captchaResult: false, bizResult: false }
        }
      },
      onBizResultCallback(bizResult) {
        if (bizResult && st().onDoneFn) st().onDoneFn()
      },
      onError() { ElMessage.error('人机验证服务异常,请稍后重试') },
    })
  })
  return ready
}

function showSdkError() {
  ready = null
  ElMessage.error('人机验证组件加载失败,请检查网络后重试')
}

onMounted(() => { init().catch(showSdkError) })  // 页面加载即预初始化,给设备采集留时间

/**
 * attach(send):注入发码函数
 *   send(phone, purpose, captchaVerifyParam) => Promise<{captchaResult, bizResult}>
 * request(phone, purpose, {onDone}):触发验证(SDK 已就绪,点击即验证)
 */
function attach(fn) { st().sendFn = fn }

async function request(phone, purpose, { onDone } = {}) {
  const S = st()
  S.currentPhone = phone
  S.currentPurpose = purpose
  S.onDoneFn = onDone || null
  try {
    await init()
    // 无痕验证形态:编程式触发静默风险判定,高风险自动降级滑块
    if (instance && typeof instance.startTracelessVerification === 'function') {
      instance.startTracelessVerification()
    } else if (instance && typeof instance.show === 'function') {
      instance.show()
    } else {
      trigger.value?.click()
    }
  } catch {
    showSdkError()
  }
}

defineExpose({ attach, request })
</script>
