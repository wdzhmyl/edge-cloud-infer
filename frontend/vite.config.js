import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 开发服务器（:5173）将 /api 代理到 FastAPI 后端（:8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
