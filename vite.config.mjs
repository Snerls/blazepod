import { defineConfig } from 'vite';
import { resolve } from 'node:path';

// Bundles the web app for both Vercel deploy and Capacitor iOS sync.
// `web/` is the source root; everything builds into `dist/`.
export default defineConfig({
  root: 'web',
  base: './',
  publicDir: false,
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      input: {
        index:   resolve(__dirname, 'web/index.html'),
        debug:   resolve(__dirname, 'web/debug.html'),
        selftest: resolve(__dirname, 'web/selftest.html'),
        test:    resolve(__dirname, 'web/test.html'),
      },
    },
  },
  server: {
    port: 8000,
  },
});
