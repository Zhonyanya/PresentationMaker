import { readFileSync } from 'node:fs'
import { describe, expect, it, vi } from 'vitest'
import JSZip from 'jszip'
import { createServerApi } from './server-api'
import { presentationSchema } from '@/domain/presentation'
import { buildPptx } from '@/export/pptx-export'

const id = '11111111-1111-4111-8111-111111111111'
const document = JSON.parse(readFileSync(new URL('../../../backend/app/ml/fixtures/all-layouts.json', import.meta.url), 'utf8'))
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

describe('серверный контракт v1', () => {
  it('общая фикстура Python проходит Zod и экспортируется редактируемым PPTX без мутации', async () => {
    const value = presentationSchema.parse(document)
    const before = JSON.stringify(value)
    const pptx = await buildPptx(value, { includeNotes: true })
    const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
    for (let n = 1; n <= 6; n++) {
      const xml = await zip.file(`ppt/slides/slide${n}.xml`)!.async('string')
      expect(xml).toContain('<p:txBody>')
      expect(xml).toContain(value.slides[n - 1].title)
    }
    expect(await zip.file('ppt/notesSlides/notesSlide3.xml')!.async('string')).toContain('Заметки докладчика')
    expect(JSON.stringify(value)).toBe(before)
  })

  it('получает CSRF, отправляет slideCount и ключ, принимает 202, а не документ', async () => {
    const mock = vi.fn().mockResolvedValueOnce(json({ csrf_token: 'csrf' })).mockResolvedValueOnce(json({ presentation_id: id, job_id: id, status_url: `/api/v1/jobs/${id}` }, 202))
    const api = createServerApi({ baseUrl: '', fetch: mock })
    const result = await api.generate({ text: 'я'.repeat(100), slideCount: 8 }, 'stable-key')
    expect(result.job_id).toBe(id)
    expect(mock.mock.calls[1][0]).toBe('/api/v1/presentations')
    expect(mock.mock.calls[1][1]).toMatchObject({ credentials: 'include', headers: { 'X-CSRF-Token': 'csrf', 'Idempotency-Key': 'stable-key' } })
    expect(JSON.parse(mock.mock.calls[1][1].body).slideCount).toBe(8)
  })

  it.each([[401, 'unauthorized'], [403, 'forbidden'], [404, 'not_found'], [409, 'conflict']])('явно различает HTTP %i', async (status, code) => {
    const api = createServerApi({ baseUrl: '', fetch: vi.fn(async () => json({ error: { code: 'SAFE_ERROR', message: 'Ошибка' } }, Number(status))) })
    await expect(api.current(id)).rejects.toMatchObject({ code, status })
  })

  it.each([[502, 'server'], [504, 'timeout'], [413, 'validation']])('HTML-ответ прокси %i даёт понятную ошибку, а не «неверный формат»', async (status, code) => {
    const api = createServerApi({ baseUrl: '', fetch: vi.fn(async () => new Response('<html>nginx</html>', { status: Number(status) })) })
    await expect(api.current(id)).rejects.toMatchObject({ code, status })
  })

  it('при устаревшем CSRF-токене берёт новый и повторяет запрос один раз', async () => {
    const accepted = { presentation_id: id, job_id: id, status_url: `/api/v1/jobs/${id}` }
    const mock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: 'old' }))
      .mockResolvedValueOnce(json({ error: { code: 'CSRF_REJECTED', message: 'Обновите сессию' } }, 403))
      .mockResolvedValueOnce(json({ csrf_token: 'new' }))
      .mockResolvedValueOnce(json(accepted, 202))
    const api = createServerApi({ baseUrl: '', fetch: mock })
    await expect(api.generate({ text: 'я'.repeat(100), slideCount: 8 }, 'same-key')).resolves.toMatchObject({ job_id: id })
    expect(mock).toHaveBeenCalledTimes(4)
    expect(mock.mock.calls[3][1]).toMatchObject({ headers: { 'X-CSRF-Token': 'new', 'Idempotency-Key': 'same-key' } })
  })

  it('другие 403 не повторяет', async () => {
    const mock = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: 'csrf' }))
      .mockResolvedValue(json({ error: { code: 'ORIGIN_REJECTED', message: 'Нет' } }, 403))
    const api = createServerApi({ baseUrl: '', fetch: mock })
    await expect(api.generate({ text: 'я'.repeat(100), slideCount: 8 }, 'k')).rejects.toMatchObject({ code: 'forbidden' })
    expect(mock).toHaveBeenCalledTimes(2)
  })

  it('список, удаление презентации и аккаунта отправляют DELETE с CSRF и экранированным ID', async () => {
    const item = { presentation_id: id, title: 'Доклад', slide_count: 6, updated_at: '2026-10-31T10:00:00+00:00', active: false }
    const mock = vi.fn()
      .mockResolvedValueOnce(json({ presentations: [item] }))
      .mockResolvedValueOnce(json({ csrf_token: 'csrf' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const api = createServerApi({ baseUrl: '', fetch: mock })
    expect(await api.list()).toEqual([item])
    await api.remove(id)
    expect(mock.mock.calls[2][0]).toBe(`/api/v1/presentations/${id}`)
    expect(mock.mock.calls[2][1]).toMatchObject({ method: 'DELETE', headers: { 'X-CSRF-Token': 'csrf' } })
    await api.deleteAccount('пароль')
    expect(mock.mock.calls[3][0]).toBe('/api/v1/auth/me')
    expect(JSON.parse(mock.mock.calls[3][1].body)).toEqual({ password: 'пароль' })
  })

  it('не принимает невалидный документ и не нормализует ID повторно', async () => {
    const api = createServerApi({ baseUrl: '', fetch: vi.fn(async () => json({ presentation_id: id, document, document_token: 'token', requested_slide_count: 8, slide_count: 6, active_job: null })) })
    expect((await api.current(id)).document?.slides.map((s) => s.id)).toEqual(document.slides.map((s: { id: string }) => s.id))
    document.slides[0].layout = 'unknown'
    await expect(api.current(id)).rejects.toMatchObject({ code: 'invalid_response' })
    document.slides[0].layout = 'title'
  })
})
