import { z } from 'zod'
import { generateRequestSchema, presentationSchema, type GenerateRequest } from '@/domain/presentation'
import { ApiError } from './errors'

const userSchema = z.object({ id: z.string().uuid(), login: z.string() })
const libraryItemSchema = z.object({
  presentation_id: z.string().uuid(), title: z.string().nullable(), slide_count: z.number().int().nullable(),
  updated_at: z.string(), active: z.boolean(),
})
const librarySchema = z.object({ presentations: z.array(libraryItemSchema) })
export type LibraryItem = z.infer<typeof libraryItemSchema>
const acceptedSchema = z.object({ presentation_id: z.string().uuid(), job_id: z.string().uuid(), status_url: z.string() })
const currentSchema = z.object({
  presentation_id: z.string().uuid(), document: presentationSchema.nullable(), document_token: z.string().nullable(),
  requested_slide_count: z.number().int(), slide_count: z.number().int().nullable(), active_job: acceptedSchema.nullable(),
})
const statusSchema = z.object({
  job_id: z.string().uuid(), presentation_id: z.string().uuid(),
  status: z.enum(['queued', 'running', 'succeeded', 'failed', 'timed_out']),
  phase: z.enum(['waiting', 'ml', 'validation', 'saving', 'done']),
  output_document_token: z.string().nullable(), error: z.object({ code: z.string(), message: z.string() }).nullable(),
})
export type ServerUser = z.infer<typeof userSchema>
export type AcceptedJob = z.infer<typeof acceptedSchema>
export type CurrentPresentation = z.infer<typeof currentSchema>
export type JobStatus = z.infer<typeof statusSchema>

export function createServerApi(config: { baseUrl: string; fetch?: typeof fetch; requestTimeoutMs?: number }) {
  const doFetch = config.fetch ?? globalThis.fetch.bind(globalThis)
  let csrfToken: string | null = null
  let identity = 0

  async function request<T>(path: string, schema: z.ZodType<T>, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController()
    const abort = () => controller.abort()
    init.signal?.addEventListener('abort', abort, { once: true })
    if (init.signal?.aborted) controller.abort()
    const timeout = setTimeout(abort, config.requestTimeoutMs ?? 20000)
    const epoch = identity
    try {
      const response = await doFetch(`${config.baseUrl}/api/v1${path}`, {
        ...init, credentials: 'include', cache: 'no-store', signal: controller.signal,
        headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
      })
      // Прокси (nginx) отвечает на 413/502/504 HTML-страницей — код ошибки берём из статуса
      const raw = response.status === 204 ? '' : await response.text()
      let body: unknown = null
      let malformed = false
      if (raw) {
        try { body = JSON.parse(raw) } catch { malformed = true }
      }
      if (epoch !== identity) throw new ApiError('aborted')
      if (!response.ok) {
        const parsed = z.object({ error: z.object({ code: z.string(), message: z.string() }), request_id: z.string().optional() }).safeParse(body)
        const code = response.status === 401 ? 'unauthorized' : response.status === 403 ? 'forbidden'
          : response.status === 404 ? 'not_found' : response.status === 409 ? 'conflict'
            : response.status === 429 ? 'rate_limited' : response.status === 408 || response.status === 504 ? 'timeout'
              : [400, 413, 422].includes(response.status) ? 'validation' : 'server'
        if (response.status === 413 && !parsed.success) {
          throw new ApiError('validation', { status: 413, message: 'Запрос слишком большой. Сократите текст и попробуйте снова.' })
        }
        if (response.status === 401 && path !== '/auth/login') {
          csrfToken = null
          globalThis.dispatchEvent?.(new Event('pm:unauthorized'))
        }
        throw new ApiError(code, { status: response.status, message: parsed.success ? parsed.data.error.message : undefined,
          details: parsed.success ? { code: parsed.data.error.code, request_id: parsed.data.request_id } : undefined })
      }
      if (malformed) throw new ApiError('invalid_response')
      const parsed = schema.safeParse(body)
      if (!parsed.success) throw new ApiError('invalid_response')
      return parsed.data
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (controller.signal.aborted) throw new ApiError(init.signal?.aborted ? 'aborted' : 'timeout')
      if (error instanceof SyntaxError) throw new ApiError('invalid_response')
      throw new ApiError('network')
    } finally {
      clearTimeout(timeout)
      init.signal?.removeEventListener('abort', abort)
    }
  }

  async function csrf() {
    const result = await request('/auth/csrf', z.object({ csrf_token: z.string() }))
    csrfToken = result.csrf_token
  }

  /** Изменяющий запрос с CSRF-токеном; POST и DELETE отличаются только методом */
  async function mutate<T>(method: 'POST' | 'DELETE', path: string, body: unknown, schema: z.ZodType<T>, key?: string, signal?: AbortSignal) {
    const send = async () => {
      if (!csrfToken) await csrf()
      return request(path, schema, { method, body: JSON.stringify(body), signal,
        headers: { 'X-CSRF-Token': csrfToken!, ...(key ? { 'Idempotency-Key': key } : {}) } })
    }
    try {
      return await send()
    } catch (error) {
      // Токен устарел (например, сессию обновили в другой вкладке): берём новый и повторяем один раз.
      // Отклонённый CSRF-запрос сервер не выполнял, так что повтор безопасен.
      const rejected = error instanceof ApiError && error.code === 'forbidden'
        && (error.details as { code?: string } | undefined)?.code === 'CSRF_REJECTED'
      if (!rejected || signal?.aborted) throw error
      csrfToken = null
      return send()
    }
  }

  const post = <T,>(path: string, body: unknown, schema: z.ZodType<T>, key?: string, signal?: AbortSignal) =>
    mutate('POST', path, body, schema, key, signal)

  return {
    forget() { identity++; csrfToken = null },
    /** Свои презентации: названия и даты, без текстов и слайдов */
    async list(signal?: AbortSignal) { return (await request('/presentations', librarySchema, { signal })).presentations },
    /** Безвозвратно стирает исходный текст и документ презентации */
    async remove(id: string) { await mutate('DELETE', `/presentations/${encodeURIComponent(id)}`, {}, z.null()) },
    /** Удаляет аккаунт со всеми данными; нужен текущий пароль */
    async deleteAccount(password: string) { await mutate('DELETE', '/auth/me', { password }, z.null()); csrfToken = null },
    /** Сессия могла смениться в другой вкладке — CSRF-токен запросить заново перед следующим POST */
    resetCsrf() { csrfToken = null },
    async me() { return (await request('/auth/me', z.object({ user: userSchema }))).user },
    async authenticate(kind: 'login' | 'register', login: string, password: string) {
      // Always obtain the current preliminary session, including after another tab logs in/out.
      await csrf()
      const result = await post(`/auth/${kind}`, { login, password }, z.object({ user: userSchema, csrf_token: z.string() }))
      csrfToken = result.csrf_token
      return result.user
    },
    async logout() { await post('/auth/logout', {}, z.null()); csrfToken = null },
    current(id: string, signal?: AbortSignal) { return request(`/presentations/${encodeURIComponent(id)}`, currentSchema, { signal }) },
    status(id: string, signal?: AbortSignal) { return request(`/jobs/${encodeURIComponent(id)}`, statusSchema, { signal }) },
    async generate(body: GenerateRequest, key: string, signal?: AbortSignal, current?: CurrentPresentation) {
      const parsed = generateRequestSchema.safeParse(body)
      if (!parsed.success) throw new ApiError('validation', { message: parsed.error.issues[0]?.message })
      return post(current ? `/presentations/${encodeURIComponent(current.presentation_id)}/generations` : '/presentations',
        { ...parsed.data, ...(current ? { base_document_token: current.document_token } : {}) }, acceptedSchema, key, signal)
    },
    revise(current: CurrentPresentation, instruction: string, targets: number[] | undefined, key: string, signal?: AbortSignal) {
      return post(`/presentations/${encodeURIComponent(current.presentation_id)}/revisions`, { instruction, target_slide_numbers: targets,
        base_document_token: current.document_token }, acceptedSchema, key, signal)
    },
  }
}
