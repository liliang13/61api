import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('lucide-vue-next') || id.includes('@element-plus/icons-vue')) return 'icons'
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('element-plus') || id.includes('@element-plus')) return 'element-plus'
          if (id.includes('qrcode')) return 'qrcode'
          if (id.includes('axios')) return 'http'
          if (/\/(vue|vue-router|pinia|@vue)\//.test(id)) return 'vue-vendor'
        },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.js'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/v1': 'http://127.0.0.1:5000',
      '/pay': 'http://127.0.0.1:5000',
    },
  },
})
