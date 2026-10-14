import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend (http://localhost:8000) allows this exact origin, so the port is fixed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    open: true, // `npm run dev` opens the desk in the browser
  },
})
