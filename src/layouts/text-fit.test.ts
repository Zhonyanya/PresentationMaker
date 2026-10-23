import { describe, expect, it } from 'vitest'
import { countLines, fitText } from './text-fit'
import { buildPresentationScenes } from './registry'
import { presentationTheme } from '@/theme/presentation-theme'
import { samplePresentation } from '@/test/fixtures'

const box = { x: 0, y: 0, w: 6, h: 2 }
const options = { max: 24, min: 12, lineSpacing: 1, paragraphSpacing: 6 }

describe('подбор размера шрифта', () => {
  it('считает строки с переносом по словам', () => {
    expect(countLines('один два три', 100)).toBe(1)
    expect(countLines('один два три', 8)).toBe(2)
    expect(countLines('один два три', 6)).toBe(3)
    expect(countLines('а'.repeat(25), 10)).toBe(3)
  })

  it('короткий текст — максимальный размер', () => {
    expect(fitText([{ text: 'Короткий текст' }], box, options)).toEqual({ fontSize: 24, overflow: false, shrunk: false })
  })

  it('длинный текст — шрифт уменьшается', () => {
    const result = fitText([{ text: 'Длинный текст '.repeat(20) }], box, options)
    expect(result.fontSize).toBeLessThan(24)
    expect(result.overflow).toBe(false)
  })

  it('слишком длинный текст — отмечается переполнение', () => {
    expect(fitText([{ text: 'Очень длинный текст '.repeat(200) }], box, options)).toMatchObject({ fontSize: 12, overflow: true })
  })

  it('все элементы всех макетов лежат в границах слайда', () => {
    const scenes = buildPresentationScenes(samplePresentation().slides, presentationTheme)
    for (const scene of scenes) {
      for (const element of scene.elements) {
        const { x, y, w, h } = element.box
        expect(x).toBeGreaterThanOrEqual(0)
        expect(y).toBeGreaterThanOrEqual(0)
        expect(x + w).toBeLessThanOrEqual(presentationTheme.slide.width + 1e-6)
        expect(y + h).toBeLessThanOrEqual(presentationTheme.slide.height + 1e-6)
      }
    }
  })
})

describe('аварийный минимум шрифта', () => {
  it('перегруженный список уменьшается ниже минимума темы, но не ниже аварийного порога', () => {
    const presentation = samplePresentation()
    const long = 'Обеспечить переход на единую модель профориентации с учётом потребностей регионального рынка труда'
    const slide = { ...presentation.slides[3], bullets: Array.from({ length: 12 }, () => `${long}, ${long}`) }
    const [scene] = buildPresentationScenes([slide], presentationTheme)
    const body = scene.elements.find((e) => e.type === 'text' && e.field === 'bullets')
    expect(body?.type).toBe('text')
    if (body?.type !== 'text') return
    expect(body.overflow).toBe(true)
    expect(body.style.fontSize).toBeLessThan(presentationTheme.typography.bullets.min)
    expect(body.style.fontSize).toBeGreaterThanOrEqual(presentationTheme.typography.absoluteMinFontSize)
  })
})
