import { generateRequestSchema, generateResponseSchema, type GenerateRequest, type Presentation } from '@/domain/presentation'
import { normalizeGenerated } from '@/domain/operations'
import { ApiError } from './errors'
import type { GenerateOptions, PresentationApi } from './types'

interface HttpApiConfig {
  baseUrl: string
  timeoutMs: number
  fetch?: typeof fetch
}

/** Тело ошибки, которое бэкенд может вернуть: { "error": { "code": "...", "message": "..." } } */
interface ErrorBody {
  error?: { code?: string; message?: string }
  message?: string
}

export function createHttpApi(config: HttpApiConfig): PresentationApi {
  const doFetch = config.fetch ?? globalThis.fetch.bind(globalThis)

  return {
    mode: 'http',
    reportsStages: false,
    async generate(request: GenerateRequest, options: GenerateOptions = {}): Promise<Presentation> {
      const parsedRequest = generateRequestSchema.safeParse(request)
      if (!parsedRequest.success) {
        throw new ApiError('validation', { message: parsedRequest.error.issues[0]?.message, details: parsedRequest.error.issues })
      }

      if (options.signal?.aborted) throw new ApiError('aborted')

      const controller = new AbortController()
      const onAbort = () => controller.abort(options.signal?.reason)
      options.signal?.addEventListener('abort', onAbort, { once: true })
      let timedOut = false
      const timer = setTimeout(() => {
        timedOut = true
        controller.abort()
      }, config.timeoutMs)

      // Таймаут и отмена действуют до конца чтения тела ответа, а не только до заголовков
      const cleanup = () => {
        clearTimeout(timer)
        options.signal?.removeEventListener('abort', onAbort)
      }
      const mapFetchError = (error: unknown) => {
        if (timedOut) return new ApiError('timeout')
        if (options.signal?.aborted) return new ApiError('aborted')
        return new ApiError('network', { details: error })
      }

      let response: Response
      let body: unknown
      try {
        response = await doFetch(`${config.baseUrl}/api/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(parsedRequest.data),
          signal: controller.signal,
        })
        body = await response.json().catch((error: unknown) => {
          if (controller.signal.aborted) throw error
          return null
        })
      } catch (error) {
        throw mapFetchError(error)
      } finally {
        cleanup()
      }

      if (!response.ok) {
        const errorBody = (body ?? {}) as ErrorBody
        const serverMessage = errorBody.error?.message ?? errorBody.message
        const code =
          response.status === 400 || response.status === 422
            ? 'validation'
            : response.status === 429
              ? 'rate_limited'
              : response.status === 408 || response.status === 504
                ? 'timeout'
                : 'server'
        throw new ApiError(code, {
          status: response.status,
          // Сообщения сервера показываем только для ошибок ввода — их пишет бэкенд для пользователя
          message: code === 'validation' && serverMessage ? serverMessage : undefined,
          details: body,
        })
      }

      const parsed = generateResponseSchema.safeParse(body)
      if (!parsed.success) {
        console.error('[api] Ответ /api/generate не соответствует контракту:', parsed.error.issues)
        throw new ApiError('invalid_response', { details: parsed.error.issues })
      }
      return normalizeGenerated(parsed.data)
    },
  }
}
