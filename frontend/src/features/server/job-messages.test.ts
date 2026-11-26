import { describe, expect, it } from 'vitest'
import { jobFailure, pollFailure, slideShortfall, STRUCTURE_COMMAND_MESSAGE } from './job-messages'

const capability = { code: 'ML_CAPABILITY_UNAVAILABLE', message: 'ML не поддерживает эту операцию.' }

describe('сообщения о результате задания', () => {
  it('отказ ML на структурную команду правки объясняется с примером рабочей команды', () => {
    expect(jobFailure(capability, 'revise')).toEqual({ message: STRUCTURE_COMMAND_MESSAGE, canRefresh: false })
    expect(STRUCTURE_COMMAND_MESSAGE).toContain('сократи пункты на слайде 3')
  })

  it('тот же код при генерации или неизвестном типе — сбой настройки, а не команда пользователя', () => {
    expect(jobFailure(capability, 'generate')).toEqual({ message: capability.message, canRefresh: false })
    expect(jobFailure(capability, null)).toEqual({ message: capability.message, canRefresh: false })
  })

  it('прочие ошибки показываются как есть, пустая — общим текстом', () => {
    expect(jobFailure({ code: 'GENERATION_FAILED', message: 'Ошибка выполнения ML.' }, 'revise').message).toBe('Ошибка выполнения ML.')
    expect(jobFailure(null, 'generate').message).toBe('Задание завершилось с ошибкой.')
  })

  it('после сбоя предлагает повторить генерацию, когда доклад есть в форме', () => {
    const invalid = { code: 'INVALID_ML_RESPONSE', message: 'ML вернул документ неверного формата.' }
    expect(jobFailure(invalid, 'generate', true)).toEqual({
      message: 'Не удалось создать презентацию. Доклад остался в форме. Нажмите «Создать презентацию», чтобы попробовать снова.',
      canRefresh: false,
    })
    expect(jobFailure(invalid, 'generate').message).toBe('Не удалось создать презентацию.')
  })

  it('пояснение о меньшем числе слайдов — только когда их правда меньше', () => {
    expect(slideShortfall({ requested_slide_count: 10, slide_count: 4 })).toBe('Получилось 4 слайда вместо 10.')
    expect(slideShortfall({ requested_slide_count: 8, slide_count: 8 })).toBeNull()
    expect(slideShortfall({ requested_slide_count: 5, slide_count: 9 })).toBeNull()
    expect(slideShortfall({ requested_slide_count: 8, slide_count: null })).toBeNull()
    expect(slideShortfall(null)).toBeNull()
  })
})

describe('сбой опроса задания', () => {
  it('временный сбой повторяется, пока есть попытки, затем ожидание ставится на паузу', () => {
    for (const code of ['network', 'timeout', 'server', 'rate_limited'] as const) {
      expect(pollFailure(code, 0, 5)).toBe('retry')
      expect(pollFailure(code, 5, 5)).toBe('pause')
    }
  })

  it('задание, статус которого не получить, перестаёт блокировать работу', () => {
    for (const code of ['not_found', 'forbidden', 'validation', 'invalid_response', 'conflict', 'unknown'] as const) {
      expect(pollFailure(code, 0, 5)).toBe('drop')
    }
  })

  it('истёкшая сессия не стирает сведения о задании', () => {
    expect(pollFailure('unauthorized', 0, 5)).toBe('pause')
  })
})
