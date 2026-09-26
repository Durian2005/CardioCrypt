import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// 构建产物直接输出到 Flask 的 static/dist，由后端托管
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/static/dist/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
    // 开发时把 API 请求代理到 Flask，避免跨域
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/manage': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/login': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/register': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/logout': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:5000', changeOrigin: true },
    },
  },
})
