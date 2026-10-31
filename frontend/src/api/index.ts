import { env } from '@/config/env'
import { ApiError } from './errors'
import { createMockApi } from './mock/mock-api'
import type { PresentationApi } from './types'

/**
 * Генератор демо-режима (VITE_API_MODE=mock). Серверный сценарий работает через
 * server-api.ts (задания и polling /api/v1) и этот интерфейс не использует.
 */
function createApi(): PresentationApi {
  if (env.apiMode === 'http') {
    return {
      mode: 'http',
      reportsStages: false,
      generate: () => Promise.reject(new ApiError('unknown', { message: 'Демо-генерация недоступна в серверном режиме.' })),
    }
  }
  const failEvery = Number(new URLSearchParams(globalThis.location?.search ?? '').get('mockFailEvery')) || undefined
  return createMockApi({ failEvery })
}

export const presentationApi: PresentationApi = createApi()

export { ApiError } from './errors'
export type { ApiErrorCode } from './errors'
export { GENERATION_STAGES } from './types'
export type { GenerationStageId, PresentationApi, GenerateOptions } from './types'
