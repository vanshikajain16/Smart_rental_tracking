import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API (backend/api/main.py) runs on :8000 with permissive CORS, so the
// dev server can call it cross-origin directly. Override the base URL with
// VITE_API_BASE if you host the API elsewhere.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
