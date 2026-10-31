/// <reference types="vitest/config" />
import path from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/** Защитные заголовки production; держать в согласии с deploy/nginx.conf */
const PRODUCTION_HEADERS = {
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // В режиме разработки запросы /api/* можно проксировать на локальный бэкенд,
  // чтобы не настраивать CORS. См. README.md, раздел серверного запуска.
  const proxyTarget = env.VITE_DEV_PROXY_TARGET

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(__dirname, './src') },
    },
    server: {
      port: 5173,
      // Не переходить незаметно на 5174: Origin должен совпадать с PM_ALLOWED_ORIGINS.
      strictPort: true,
      ...(proxyTarget ? { proxy: { '/api': { target: proxyTarget, changeOrigin: true } } } : {}),
      // Dev-сервер внедряет inline-скрипты (HMR), поэтому без CSP — только запрет встраивания
      headers: { 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' },
    },
    // Предпросмотр сборки с теми же заголовками, что отдаёт nginx (deploy/nginx.conf)
    preview: { headers: PRODUCTION_HEADERS },
    build: {
      // Основной бандл ~850 КБ (~270 КБ в gzip): React, Radix, motion, dnd-kit, Zod.
      // PptxGenJS и mammoth подгружаются динамически, только при экспорте и импорте DOCX.
      chunkSizeWarningLimit: 900,
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  }
})
