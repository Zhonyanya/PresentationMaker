import { env } from '@/config/env'
import { createHttpApi } from './http-api'
import { createMockApi } from './mock/mock-api'
import type { PresentationApi } from './types'

/**
 * Выбор реализации API по переменной окружения VITE_API_MODE.
 * Компоненты импортируют только `presentationApi` и типы — переписывать их
 * при подключении бэкенда не нужно.
 */
function createApi(): PresentationApi {
  if (env.apiMode === 'http') {
    return createHttpApi({ baseUrl: env.apiBaseUrl, timeoutMs: env.apiTimeoutMs })
  }
  const failEvery = Number(new URLSearchParams(globalThis.location?.search ?? '').get('mockFailEvery')) || undefined
  return createMockApi({ failEvery })
}

export const presentationApi: PresentationApi = createApi()

export { ApiError } from './errors'
export type { ApiErrorCode } from './errors'
export { GENERATION_STAGES } from './types'
export type { GenerationStageId, PresentationApi, GenerateOptions } from './types'
