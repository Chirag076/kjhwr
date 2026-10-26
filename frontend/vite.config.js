import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the API runs in its own container; the proxy keeps the
// browser on one origin so there is no CORS dance while iterating.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
