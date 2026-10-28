import { describe, expect, it } from 'vitest'
import { generateResponseSchema } from '@/domain/presentation'
import { demoExamples } from '@/data/demo-examples'
import { generateMockPresentation } from './mock-generator'
import { parseSource, splitSentences, toBullet } from './text-analysis'

describe('анализ текста', () => {
  it('выделяет заголовки, абзацы и списки', () => {
    const parsed = parseSource('Отчёт\n\nПервый раздел\nТекст раздела про школы.\n\nВторой раздел\n- пункт один\n- пункт два')
    expect(parsed.title).toBe('Отчёт')
    expect(parsed.blocks.map((b) => b.heading)).toEqual(['Первый раздел', 'Второй раздел'])
    expect(parsed.blocks[1].items).toEqual(['пункт один', 'пункт два'])
  })

  it('не режет предложения на сокращениях', () => {
    expect(splitSentences('Открыты кружки, секции и т. д. Работа продолжается.')).toHaveLength(2)
  })

  it('превращает предложение в пункт без вводных слов и точки', () => {
    expect(toBullet('Кроме того, открыты новые центры.')).toBe('Открыты новые центры')
  })
})

describe('демо-генератор', () => {
  it.each(demoExamples)('$label — валидный ответ по контракту', (example) => {
    const response = generateMockPresentation({ text: example.text, title: example.title || undefined, slideCount: example.slideCount })
    expect(generateResponseSchema.safeParse(response).success).toBe(true)
    expect(response.slides[0].layout).toBe('title')
    expect(response.slides.at(-1)?.layout).toBe('closing')
    // Количество слайдов близко к запрошенному
    expect(Math.abs(response.slides.length - example.slideCount)).toBeLessThanOrEqual(2)
  })

  it('использует содержание исходного текста, а не шаблон', () => {
    const response = generateMockPresentation({ text: demoExamples[1].text, slideCount: 7 })
    const allText = JSON.stringify(response.slides)
    expect(allText).toContain('Что показала региональная диагностика')
    expect(allText).toContain('Сетевые проекты между школами')
  })

  it('находит пары «Проблемы / Решения» и делает две колонки', () => {
    const response = generateMockPresentation({ text: demoExamples[0].text, slideCount: 8 })
    const columns = response.slides.find((s) => s.layout === 'two-column')
    expect(columns).toMatchObject({ leftTitle: 'Проблемы', rightTitle: 'Решения' })
  })

  it('берёт название из запроса, если оно указано', () => {
    const response = generateMockPresentation({ text: demoExamples[2].text, title: 'Моё название', slideCount: 6 })
    expect(response.title).toBe('Моё название')
    expect(response.slides[0].title).toBe('Моё название')
  })

  it('справляется с текстом без структуры', () => {
    const text = 'Это сплошной текст без заголовков. '.repeat(30)
    const response = generateMockPresentation({ text, slideCount: 5 })
    expect(generateResponseSchema.safeParse(response).success).toBe(true)
    expect(response.slides.length).toBeGreaterThanOrEqual(3)
  })
})
