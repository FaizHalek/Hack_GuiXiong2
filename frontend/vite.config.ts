/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The SPA calls the API at /api on its own origin; in development Vite forwards those calls to
// the FastAPI server. Override the target with API_PROXY_TARGET if the backend runs elsewhere.
const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8000'

const apiProxy = {
  '/api': {
    target: apiTarget,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: apiProxy,
    // Accept requests forwarded by dev tunnels / port forwarding (their Host header isn't localhost).
    allowedHosts: true,
  },
  preview: {
    proxy: apiProxy,
    allowedHosts: true,
  },
  build: {
    chunkSizeWarningLimit: 800,
  },
  test: {
    environment: 'node',
  },
})
