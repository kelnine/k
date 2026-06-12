import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // GitHub Pages serves the site under /<repo>/; CI sets VITE_BASE accordingly
  base: process.env.VITE_BASE ?? '/',
  server: { host: true },
})
