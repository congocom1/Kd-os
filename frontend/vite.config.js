import { defineConfig } from 'vite';

export default defineConfig({
  root: '.',
  base: '/static/',
  publicDir: 'public',
  build: {
    outDir: '../dashboard/static',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: 'index.html',
        dashboard: 'dashboard.html',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://localhost:8001',
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: 'wss://localhost:8001',
        ws: true,
        secure: false,
      },
    },
  },
});