/**
 * Конфигурация окружения. Значения задаются в .env (см. .env.example).
 * Секретов здесь быть не может: всё, что начинается с VITE_, попадает в браузер.
 */

export type ApiMode = 'mock' | 'http'

function readMode(value: string | undefined): ApiMode {
  return value === 'http' ? 'http' : 'mock'
}

export const env = {
  apiMode: readMode(import.meta.env.VITE_API_MODE),
  /** Базовый URL бэкенда без завершающего слэша. Пусто — тот же домен. */
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, ''),
} as const
