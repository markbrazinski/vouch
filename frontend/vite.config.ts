import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // The browser only ever talks to same-origin /api. In production that is
    // API Gateway -> Lambda BFF; in development it is scripts/local_bff.py,
    // which imports the SAME handler. The frontend cannot tell the difference,
    // and deliberately holds no AWS SDK either way.
    proxy: {
      '/api': {
        target: process.env.VOUCH_BFF ?? 'http://127.0.0.1:8787',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
