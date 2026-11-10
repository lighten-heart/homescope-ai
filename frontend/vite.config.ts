import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  // 启用 Vue 插件
  plugins: [vue()],

  // 设置前端访问地址
  server: {
    host: '127.0.0.1',
    port: 5173,

    // 端口被占用就报错，避免悄悄换端口。
    strictPort: true,

    // 当前端开发服务器收到以/api开头的请求时，将请求转发到后端8000端口。
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,

        // 后端分析耗时较长，避免代理过早放弃等待。
        proxyTimeout: 960_000,
      },
    },
  },
})
                                 