import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Dev: `npm run dev` proxies API calls to the FastAPI server on :8080.
// Prod: `npm run build` -> dist/, which api/main.py serves directly.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/cards': 'http://localhost:8080',
    },
  },
});
