import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev: the FastAPI backend owns /api and /webhooks.
    proxy: {
      '/api': 'http://localhost:8000',
      '/webhooks': 'http://localhost:8000',
    },
  },
})
