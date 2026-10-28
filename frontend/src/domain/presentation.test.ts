import { describe, expect, it } from 'vitest'
import { generateRequestSchema, generateResponseSchema, presentationSchema, SLIDE_LAYOUTS } from './presentation'
import { normalizeGenerated } from './operations'
import { layoutRegistry } from '@/layouts/registry'

const contractExample = {
  title: 'Итоги учебного года',
  slides: [
    { id: 'slide-1', layout: 'title', title: 'Итоги учебного года', subtitle: 'Основные результаты' },
    { id: 'slide-2', layout: 'bullets', title: 'Ключевые достижения', bullets: ['Первое', 'Второе', 'Третье'], notes: 'Дополнительная информация' },
    { id: 'slide-3', layout: 'two-column', title: 'Основные направления', left: ['Направление 1'], right: ['Направление 2'] },
    { id: 'slide-4', layout: 'closing', title: 'Спасибо за внимание' },
  ],
}

describe('контракт API', () => {
  it('принимает пример ответа из ТЗ', () => {
    expect(generateResponseSchema.safeParse(contractExample).success).toBe(true)
  })

  it('разрешает не передавать id и пустые списки', () => {
    const parsed = generateResponseSchema.parse({
      title: 'Т',
      slides: [{ layout: 'bullets', title: 'Без пунктов' }, { layout: 'two-column', title: 'Колонки' }],
    })
    const presentation = normalizeGenerated(parsed)
    expect(presentation.slides.every((s) => s.id.length > 0)).toBe(true)
    expect(presentation.slides[0]).toMatchObject({ bullets: [] })
    expect(presentationSchema.safeParse(presentation).success).toBe(true)
  })

  it('делает повторяющиеся id уникальными', () => {
    const parsed = generateResponseSchema.parse({
      title: 'Т',
      slides: [
        { id: 'dup', layout: 'section', title: 'А' },
        { id: 'dup', layout: 'section', title: 'Б' },
      ],
    })
    const ids = normalizeGenerated(parsed).slides.map((s) => s.id)
    expect(new Set(ids).size).toBe(2)
  })

  it('отклоняет неизвестный макет и пустую презентацию', () => {
    expect(generateResponseSchema.safeParse({ title: 'Т', slides: [{ layout: 'chart', title: 'X' }] }).success).toBe(false)
    expect(generateResponseSchema.safeParse({ title: 'Т', slides: [] }).success).toBe(false)
  })

  it('проверяет запрос: длина текста и количество слайдов', () => {
    expect(generateRequestSchema.safeParse({ text: 'коротко', slideCount: 8 }).success).toBe(false)
    expect(generateRequestSchema.safeParse({ text: 'а'.repeat(200), slideCount: 2 }).success).toBe(false)
    expect(generateRequestSchema.safeParse({ text: 'а'.repeat(200), slideCount: 8 }).success).toBe(true)
  })

  it('у каждого макета из схемы есть определение в реестре', () => {
    for (const layout of SLIDE_LAYOUTS) expect(layoutRegistry[layout]?.layout).toBe(layout)
  })
})
