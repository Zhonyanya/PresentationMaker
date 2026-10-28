import { generateRequestSchema, generateResponseSchema, type GenerateRequest, type Presentation } from '@/domain/presentation'
import { normalizeGenerated } from '@/domain/operations'
import { ApiError } from '../errors'
import { GENERATION_STAGES, type GenerateOptions, type PresentationApi } from '../types'
import { generateMockPresentation } from './mock-generator'

interface MockApiConfig {
  /** Пауза на каждом этапе, мс. 0 — мгновенно (для тестов). */
  stageDelayMs?: number
  /** Если задано — каждый N-й запрос завершается ошибкой. Для проверки экранов ошибок. */
  failEvery?: number
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new ApiError('aborted'))
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new ApiError('aborted'))
      },
      { once: true },
    )
  })
}

/**
 * Демонстрационная реализация API: работает целиком в браузере.
 * Этапы имитируются по таймеру — интерфейс помечает это как демо.
 */
export function createMockApi(config: MockApiConfig = {}): PresentationApi {
  const stageDelay = config.stageDelayMs ?? 750
  let calls = 0

  return {
    mode: 'mock',
    reportsStages: true,
    async generate(request: GenerateRequest, options: GenerateOptions = {}): Promise<Presentation> {
      const parsedRequest = generateRequestSchema.safeParse(request)
      if (!parsedRequest.success) {
        throw new ApiError('validation', { message: parsedRequest.error.issues[0]?.message, details: parsedRequest.error.issues })
      }
      calls += 1

      let response: unknown = null
      for (const [index, stage] of GENERATION_STAGES.entries()) {
        options.onStage?.(stage.id)
        await wait(stageDelay * (index === 2 ? 1.6 : 1), options.signal)
        if (stage.id === 'structure') response = generateMockPresentation(parsedRequest.data)
        if (config.failEvery && calls % config.failEvery === 0 && stage.id === 'slides') {
          throw new ApiError('server', { details: 'Сымитированная ошибка демо-режима' })
        }
      }

      // Ответ mock-генератора проходит ту же проверку, что и ответ сервера
      const parsed = generateResponseSchema.safeParse(response)
      if (!parsed.success) throw new ApiError('invalid_response', { details: parsed.error.issues })
      return normalizeGenerated(parsed.data)
    },
  }
}
