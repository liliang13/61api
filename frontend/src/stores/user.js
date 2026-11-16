import { defineStore } from 'pinia'
import { getMe, getSiteInfo, logout as requestLogout } from '../api'

export const useUserStore = defineStore('user', {
  state: () => ({
    info: null,
    site: null,
    sitePromise: null,
    restored: false,
    restorePromise: null,
  }),
  getters: {
    isLogin: (s) => !!s.info,
    isAdmin: (s) => s.info?.role === 'admin',
    isPrivate: (s) => !!s.site?.private,
    siteName: (s) => s.site?.site_name || '61API',
  },
  actions: {
    async ensureSite() {
      if (this.site) return this.site
      if (!this.sitePromise) {
        this.sitePromise = getSiteInfo()
          .then((res) => { this.site = res.data; return this.site })
          .catch(() => null)
          .finally(() => { this.sitePromise = null })
      }
      return this.sitePromise
    },
    feature(name) {
      if (!this.site?.features) return true
      return this.site.features[name] !== false
    },
    clearSession() {
      this.info = null
      this.restored = true
    },
    async fetchMe() {
      try {
        const res = await getMe()
        this.info = res.data
        this.restored = true
        return this.info
      } catch (error) {
        if (error.response?.status === 401) {
          this.clearSession()
          return null
        }
        throw error
      }
    },
    async restoreSession() {
      if (this.restored) return this.info
      if (!this.restorePromise) {
        this.restorePromise = this.fetchMe().finally(() => { this.restorePromise = null })
      }
      return this.restorePromise
    },
    async logout() {
      try {
        await requestLogout()
        return true
      } catch {
        return false
      } finally {
        this.clearSession()
      }
    },
  },
})
