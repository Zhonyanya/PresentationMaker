export type ApiErrorCode =
  | 'validation' // запрос не прошёл проверку на клиенте или сервер вернул 400/422
  | 'network' // нет соединения с сервером
  | 'timeout' // сервер не ответил за отведённое время
  | 'aborted' // пользователь отменил генерацию
  | 'rate_limited' // 429
  | 'server' // 5xx или иная ошибка сервера
  | 'invalid_response' // ответ не соответствует контракту
  | 'unknown'

const DEFAULT_MESSAGES: Record<ApiErrorCode, string> = {
  validation: 'Проверьте исходный текст и параметры презентации.',
  network: 'Не удалось связаться с сервером. Проверьте подключение к сети и попробуйте ещё раз.',
  timeout: 'Сервер не успел подготовить презентацию. Попробуйте ещё раз или сократите текст.',
  aborted: 'Генерация отменена.',
  rate_limited: 'Слишком много запросов. Подождите минуту и попробуйте снова.',
  server: 'На сервере произошла ошибка. Попробуйте ещё раз чуть позже.',
  invalid_response: 'Сервер вернул данные в неожиданном формате. Сообщите об этом разработчикам.',
  unknown: 'Что-то пошло не так. Попробуйте ещё раз.',
}

export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly status?: number
  /** Технические подробности — для консоли и отчёта разработчикам, не для пользователя */
  readonly details?: unknown

  constructor(code: ApiErrorCode, options: { message?: string; status?: number; details?: unknown } = {}) {
    super(options.message ?? DEFAULT_MESSAGES[code])
    this.name = 'ApiError'
    this.code = code
    this.status = options.status
    this.details = options.details
  }

  get retryable(): boolean {
    return this.code !== 'validation' && this.code !== 'aborted'
  }
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (error instanceof DOMException && error.name === 'AbortError') return new ApiError('aborted')
  return new ApiError('unknown', { details: error })
}
