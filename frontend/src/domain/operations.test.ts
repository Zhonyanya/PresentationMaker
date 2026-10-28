import { describe, expect, it } from 'vitest'
import { samplePresentation } from '@/test/fixtures'
import { canSplitSlide, convertSlide, createSlide, duplicateSlide, insertSlide, moveSlide, removeSlide, splitSlide, updateSlide } from './operations'
import { presentationSchema, SLIDE_LAYOUTS } from './presentation'

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
