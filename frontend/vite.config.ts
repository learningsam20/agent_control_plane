import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Control plane API location. Same origin in dev/preview (proxied below),
// or a separately-hosted instance via CONTROLPLANE_API_URL.
const API_TARGET = process.env.CONTROLPLANE_API_URL || 'http://localhost:5186'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5185,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
  preview: {
    port: 5185,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
    },
  },
})
