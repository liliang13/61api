import axios from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'
import router from '../router'

const http = axios.create({ baseURL: '/api', timeout: 60000, withCredentials: true })

http.interceptors.request.use((config) => {
  if (!['get', 'head', 'options'].includes((config.method || 'get').toLowerCase())) {
    config.headers['X-Requested-With'] = 'XMLHttpRequest'
  }
  return config
})

http.interceptors.response.use(
  (resp) => {
    const data = resp.data
    if (data && data.ok === false) {
      ElMessage.error(data.error || '请求失败')
      return Promise.reject(new Error(data.error || '请求失败'))
    }
    return data
  },
  async (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.error || error.response?.data?.message || '网络错误,请稍后重试'
    if (status === 401) {
      useUserStore().clearSession()
      // 公开页(首页/文档等)不要求登录:会话探测 401 是正常态,静默处理;
      // 仅当前路由要求登录时才提示并跳登录页。强刷首个导航期间 currentRoute
      // 尚未就绪,此时由路由守卫按 to.meta.auth 兜底跳转。
      if (router.currentRoute.value.meta.auth && !location.pathname.startsWith('/login')) {
        ElMessage.error('登录已过期,请重新登录')
        setTimeout(() => location.assign('/login'), 600)
      }
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export default http
