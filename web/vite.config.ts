import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

// In development the Python server runs on :8000 (python main.py); Vite proxies to it.
const backend = 'http://localhost:8000';

export default defineConfig({
  plugins: [preact()],
  server: {
    proxy: {
      '/api': backend,
      '/login': backend,
      '/logout': backend,
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
