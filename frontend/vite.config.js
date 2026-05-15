import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true
      },
      '/files': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    // 提高首屏性能：重体积三方库拆出独立 chunk，允许浏览器并行下载与独立缓存
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          // Vue 生态独立 chunk（顶点依赖，变更频率低，合适长期缓存）
          'vue-vendor': ['vue', 'pinia'],
          // vue-flow 论证逻辑图仅在 KeypointsTab 展开时生效，单独拆包避免首屏加载
          'vue-flow': [
            '@vue-flow/core',
            '@vue-flow/background',
            '@vue-flow/controls',
            '@vue-flow/minimap'
          ],
          // mammoth 仅在打开 .docx/.doc 文档时需要；marked 仅 AI 对话渲染需要
          'doc-render': ['mammoth', 'marked']
        }
      }
    }
  }
})
