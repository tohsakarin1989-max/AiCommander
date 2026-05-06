import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/react') || id.includes('/react-dom') || id.includes('/react-router-dom')) {
            return 'vendor-react'
          }
          if (id.includes('/antd') || id.includes('@ant-design')) {
            return 'vendor-antd'
          }
          if (id.includes('/echarts')) {
            return 'vendor-echarts'
          }
          if (id.includes('/leaflet')) {
            return 'vendor-map'
          }
          if (id.includes('@tanstack') || id.includes('/axios') || id.includes('/dayjs')) {
            return 'vendor-runtime'
          }
          return 'vendor'
        },
      },
    },
  },
})
