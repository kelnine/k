import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The API runs separately (`kterminal api`, default http://127.0.0.1:8000). In
// development and `vite preview` the dashboard proxies /api and /health to it, so
// the session cookie stays first-party exactly as behind Caddy in production.
const api = process.env.KT_API_URL ?? 'http://127.0.0.1:8000'
const proxy = {
  '/api': { target: api, changeOrigin: false },
  '/health': { target: api, changeOrigin: false },
}

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 600 },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
