import { defineConfig } from 'vite';

// Tauri 只需要 Vite 做前端打包；strictPort 保证 devUrl 与 tauri.conf.json 一致。
export default defineConfig({
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    // 人设 system prompt 直接引用训练语料里的原文，避免两份口径漂移。
    fs: { allow: ['..'] },
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    target: 'es2022',
    sourcemap: false,
  },
});
