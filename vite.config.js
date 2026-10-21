import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Local development: the FastAPI app runs on :8000 (see README).
    proxy: { '/api': 'http://localhost:8000' },
  },
})
