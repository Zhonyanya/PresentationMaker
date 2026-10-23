/// <reference types="vitest/config" />
import path from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // В режиме разработки запросы /api/* можно проксировать на локальный бэкенд,
  // чтобы не настраивать CORS. См. BACKEND_INTEGRATION.md.
  const proxyTarget = env.VITE_DEV_PROXY_TARGET

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: proxyTarget
      ? { proxy: { '/api': { target: proxyTarget, changeOrigin: true } } }
      : undefined,
    build: {
      // Основной бандл ~200 КБ gzip (React, Radix, dnd-kit, Zod) — в пределах бюджета приложения.
      // PptxGenJS и mammoth подгружаются динамически, только при экспорте и импорте DOCX.
      chunkSizeWarningLimit: 700,
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  }
})
