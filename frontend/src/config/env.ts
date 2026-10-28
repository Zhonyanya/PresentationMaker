/**
 * Конфигурация окружения. Значения задаются в .env (см. .env.example).
 * Секретов здесь быть не может: всё, что начинается с VITE_, попадает в браузер.
 */

export type ApiMode = 'mock' | 'http'

const DEFAULT_TIMEOUT_MS = 25 * 60 * 1000

function readMode(value: string | undefined): ApiMode {
  return value === 'http' ? 'http' : 'mock'
}

function readNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

export const env = {
  apiMode: readMode(import.meta.env.VITE_API_MODE),
  /** Базовый URL бэкенда без завершающего слэша. Пусто — тот же домен. */
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, ''),
  apiTimeoutMs: readNumber(import.meta.env.VITE_API_TIMEOUT_MS, DEFAULT_TIMEOUT_MS),
} as const
