import { describe, expect, it, vi } from 'vitest'
import { createHttpApi } from './http-api'
import { ApiError } from './errors'

const request = { text: 'а'.repeat(200), title: 'Тест', slideCount: 6 }
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function api(fetchImpl: typeof fetch, timeoutMs = 5000) {
  return createHttpApi({ baseUrl: 'https://api.example.test', timeoutMs, fetch: fetchImpl })
}

describe('HTTP API', () => {
  it('отправляет POST /api/generate и нормализует ответ', async () => {
    const fetchMock = vi.fn(async () => json({ title: 'Тест', slides: [{ layout: 'title', title: 'Тест' }] }))
    const result = await api(fetchMock as unknown as typeof fetch).generate(request)
    expect(fetchMock).toHaveBeenCalledWith('https://api.example.test/api/generate', expect.objectContaining({ method: 'POST' }))
    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect(body).toEqual(request)
    expect(result.slides[0].id).toBeTruthy()
  })

  it('не отправляет невалидный запрос', async () => {
    const fetchMock = vi.fn()
    await expect(api(fetchMock as unknown as typeof fetch).generate({ ...request, text: 'мало' })).rejects.toMatchObject({ code: 'validation' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    [422, 'validation'],
    [429, 'rate_limited'],
    [504, 'timeout'],
    [500, 'server'],
  ])('HTTP %i → %s', async (status, code) => {
    const fetchMock = vi.fn(async () => json({ error: { message: 'Текст слишком короткий' } }, status))
    await expect(api(fetchMock as unknown as typeof fetch).generate(request)).rejects.toMatchObject({ code })
  })

  it('показывает сообщение сервера для ошибок ввода', async () => {
    const fetchMock = vi.fn(async () => json({ error: { code: 'TEXT_TOO_SHORT', message: 'Текст слишком короткий' } }, 422))
    await expect(api(fetchMock as unknown as typeof fetch).generate(request)).rejects.toThrow('Текст слишком короткий')
  })

  it('ответ не по контракту → invalid_response', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const fetchMock = vi.fn(async () => json({ slides: 'не массив' }))
    await expect(api(fetchMock as unknown as typeof fetch).generate(request)).rejects.toMatchObject({ code: 'invalid_response' })
  })

  it('сетевая ошибка → network', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    })
    await expect(api(fetchMock as unknown as typeof fetch).generate(request)).rejects.toMatchObject({ code: 'network' })
  })

  it('таймаут и отмена', async () => {
    const hanging = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_, reject) => init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))),
    )
    await expect(api(hanging as unknown as typeof fetch, 20).generate(request)).rejects.toMatchObject({ code: 'timeout' })

    const controller = new AbortController()
    const promise = api(hanging as unknown as typeof fetch).generate(request, { signal: controller.signal })
    controller.abort()
    const error = await promise.catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('aborted')
    expect((error as ApiError).retryable).toBe(false)
  })

  it('таймаут действует и пока читается тело ответа', async () => {
    const slowBody = vi.fn(async (_url: string, init?: RequestInit) => {
      const stream = new ReadableStream({
        start(controller) {
          init?.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')))
        },
      })
      return new Response(stream, { status: 200 })
    })
    await expect(api(slowBody as unknown as typeof fetch, 30).generate(request)).rejects.toMatchObject({ code: 'timeout' })
  })

  it('уже отменённый запрос не отправляется', async () => {
    const fetchMock = vi.fn()
    const controller = new AbortController()
    controller.abort()
    await expect(api(fetchMock as unknown as typeof fetch).generate(request, { signal: controller.signal })).rejects.toMatchObject({ code: 'aborted' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
