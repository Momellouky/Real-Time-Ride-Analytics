import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '');
  return {
    plugins: [vue()],
    envDir: '..',
    define: {
      'import.meta.env.VITE_DASHBOARD_POLL_INTERVAL_MS': JSON.stringify(
        env.VITE_DASHBOARD_POLL_INTERVAL_MS || env.DASHBOARD_POLL_INTERVAL_MS || '2000'),
    },
    server: {
      port: 5173,
      proxy: { '/api': { target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000' } },
    },
    test: { include: ['tests/**/*.test.js'], environment: 'node' },
  };
});
