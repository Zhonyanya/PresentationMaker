import { describe, expect, it } from 'vitest'
import { samplePresentation } from '@/test/fixtures'
import {
  canSplitSlide,
  convertLosesContent,
  convertSlide,
  createSlide,
  duplicateSlide,
  fitPresentation,
  fitSlide,
  insertSlide,
  MAX_SLIDES,
  moveSlide,
  removeSlide,
  splitSlide,
  updateSlide,
} from './operations'
import { presentationSchema, slideSchema, SLIDE_LAYOUTS, type Slide } from './presentation'

const long = (n: number) => 'я'.repeat(n)
const list = (n: number) => Array.from({ length: n }, (_, i) => `Пункт ${i + 1}`)

describe('пределы схемы в редакторе', () => {
  it('fitSlide приводит перегруженный слайд любого макета к схеме', () => {
    const oversized: Slide[] = [
      { id: 'a', layout: 'title', title: long(500), subtitle: long(900), caption: long(500), notes: long(20_000) },
      { id: 'b', layout: 'text', title: long(500), body: long(9000) },
      { id: 'c', layout: 'bullets', title: 'x', bullets: [...list(20), long(3000)] },
      { id: 'd', layout: 'two-column', title: 'x', leftTitle: long(300), rightTitle: long(300), left: list(30), right: list(30) },
      { id: 'e', layout: 'section', title: 'x', subtitle: long(900) },
      { id: 'f', layout: 'closing', title: 'x', subtitle: long(900) },
    ]
    for (const slide of oversized) expect(slideSchema.safeParse(fitSlide(slide)).success, slide.layout).toBe(true)
  })

  it('fitSlide и fitPresentation не трогают документ в пределах схемы', () => {
    const presentation = samplePresentation()
    expect(fitPresentation(presentation)).toBe(presentation)
    for (const slide of presentation.slides) expect(fitSlide(slide)).toBe(slide)
  })

  it('смена две колонки → список с 24 пунктами даёт валидный слайд и сообщает об обрезке', () => {
    const slide: Slide = { id: 'tc', layout: 'two-column', title: 'Сравнение', left: list(12), right: list(12) }
    const converted = convertSlide(slide, 'bullets')
    expect(slideSchema.safeParse(converted).success).toBe(true)
    expect(convertLosesContent(slide, 'bullets')).toBe(true)
    expect(convertLosesContent({ ...slide, left: list(3), right: list(3) }, 'bullets')).toBe(false)
  })

  it('разделение слайда с заголовком у предела не выходит за схему', () => {
    const base = samplePresentation()
    const slides = base.slides.map((s) => (s.id === 's4' ? { ...s, title: long(198) } : s))
    const { presentation, newId } = splitSlide({ ...base, slides }, 's4')
    expect(newId).not.toBeNull()
    expect(presentationSchema.safeParse(presentation).success).toBe(true)
  })

  it('не даёт превысить 60 слайдов', () => {
    const base = samplePresentation()
    const full = { ...base, slides: Array.from({ length: MAX_SLIDES }, (_, i) => ({ ...base.slides[3], id: `n${i}` })) }
    expect(insertSlide(full, createSlide('text'), 0)).toBe(full)
    expect(duplicateSlide(full, 'n0').newId).toBeNull()
    expect(splitSlide(full, 'n0').newId).toBeNull()
  })
})

describe('операции редактора', () => {
  it('не мутируют исходную презентацию', () => {
    const original = samplePresentation()
    const snapshot = structuredClone(original)
    updateSlide(original, 's3', { title: 'Новый' })
    moveSlide(original, 0, 3)
    removeSlide(original, 's4')
    expect(original).toEqual(snapshot)
  })

  it('обновляет поля слайда, но не id и макет', () => {
    const next = updateSlide(samplePresentation(), 's4', { title: 'Обновлено', id: 'x', layout: 'text' } as never)
    expect(next.slides[3]).toMatchObject({ id: 's4', layout: 'bullets', title: 'Обновлено' })
  })

  it('дублирует слайд сразу после оригинала с новым id', () => {
    const { presentation, newId } = duplicateSlide(samplePresentation(), 's4')
    expect(presentation.slides).toHaveLength(7)
    expect(presentation.slides[4].id).toBe(newId)
    expect(newId).not.toBe('s4')
    expect(presentation.slides[4]).toMatchObject({ layout: 'bullets', bullets: ['Первое', 'Второе', 'Третье', 'Четвёртое'] })
  })

  it('удаляет слайд, но не последний', () => {
    expect(removeSlide(samplePresentation(), 's4').slides.map((s) => s.id)).not.toContain('s4')
    const single = { title: 'Т', slides: [samplePresentation().slides[0]] }
    expect(removeSlide(single, 's1').slides).toHaveLength(1)
  })

  it('переставляет слайды', () => {
    const ids = moveSlide(samplePresentation(), 5, 1).slides.map((s) => s.id)
    expect(ids).toEqual(['s1', 's6', 's2', 's3', 's4', 's5'])
  })

  it('вставляет слайд в заданную позицию и ограничивает индекс', () => {
    const slide = createSlide('section')
    expect(insertSlide(samplePresentation(), slide, 2).slides[2].id).toBe(slide.id)
    expect(insertSlide(samplePresentation(), slide, 99).slides.at(-1)?.id).toBe(slide.id)
  })

  it('создаёт валидный пустой слайд любого макета', () => {
    for (const layout of SLIDE_LAYOUTS) {
      const slide = createSlide(layout)
      expect(slide.layout).toBe(layout)
      expect(presentationSchema.safeParse({ title: 'Т', slides: [slide] }).success).toBe(true)
    }
  })

  it('при смене макета сохраняет текст', () => {
    const bullets = samplePresentation().slides[3]
    const columns = convertSlide(bullets, 'two-column')
    expect(columns).toMatchObject({ id: 's4', layout: 'two-column', title: 'Достижения', left: ['Первое', 'Второе'], right: ['Третье', 'Четвёртое'] })
    const back = convertSlide(columns, 'bullets')
    expect(back).toMatchObject({ bullets: ['Первое', 'Второе', 'Третье', 'Четвёртое'] })
    const text = convertSlide(back, 'text')
    expect(text).toMatchObject({ body: 'Первое\nВторое\nТретье\nЧетвёртое' })
  })

  it('делит перегруженный список на два слайда', () => {
    const { presentation, newId } = splitSlide(samplePresentation(), 's4')
    expect(presentation.slides).toHaveLength(7)
    expect(presentation.slides[3]).toMatchObject({ bullets: ['Первое', 'Второе'] })
    expect(presentation.slides[4]).toMatchObject({ id: newId, title: 'Достижения (продолжение)', bullets: ['Третье', 'Четвёртое'] })
  })

  it('не делит слайды без содержимого для разделения', () => {
    const p = samplePresentation()
    expect(canSplitSlide(p.slides[0])).toBe(false)
    expect(splitSlide(p, 's1').newId).toBeNull()
    expect(canSplitSlide(p.slides[2])).toBe(true)
  })
})
