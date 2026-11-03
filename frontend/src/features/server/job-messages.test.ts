import { describe, expect, it } from 'vitest'
import { jobErrorMessage, slideShortfall, STRUCTURE_COMMAND_MESSAGE } from './job-messages'

describe('сообщения о результате задания', () => {
  it('отказ ML на структурную команду объясняется с примером рабочей команды', () => {
    expect(jobErrorMessage({ code: 'ML_CAPABILITY_UNAVAILABLE', message: 'ML не поддерживает эту операцию.' })).toBe(STRUCTURE_COMMAND_MESSAGE)
    expect(STRUCTURE_COMMAND_MESSAGE).toContain('сократи пункты на слайде 3')
  })

  it('прочие ошибки показываются как есть, пустая — общим текстом', () => {
    expect(jobErrorMessage({ code: 'GENERATION_FAILED', message: 'Ошибка выполнения ML.' })).toBe('Ошибка выполнения ML.')
    expect(jobErrorMessage(null)).toContain('Предыдущий документ сохранён')
  })

  it('пояснение о меньшем числе слайдов — только когда их правда меньше', () => {
    expect(slideShortfall({ requested_slide_count: 10, slide_count: 4 })).toMatch(/^Получилось 4 слайда вместо 10:/)
    expect(slideShortfall({ requested_slide_count: 8, slide_count: 8 })).toBeNull()
    expect(slideShortfall({ requested_slide_count: 5, slide_count: 9 })).toBeNull()
    expect(slideShortfall({ requested_slide_count: 8, slide_count: null })).toBeNull()
    expect(slideShortfall(null)).toBeNull()
  })
})
