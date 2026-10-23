import type { Presentation, Slide, SlideLayout, SlideOf } from './presentation'
import type { GenerateResponse } from './presentation'
import { getLayout } from '@/layouts/registry'
import type { LayoutDefinition, SlideContent } from '@/layouts/types'
import { createId } from './ids'
import { splitInHalf, paragraphsOf } from '@/layouts/content-utils'

/**
 * Чистые операции над презентацией. Не мутируют аргументы —
 * всегда возвращают новый объект. Используются хранилищем редактора
 * и покрыты тестами (operations.test.ts).
 */

export function extractContent(slide: Slide): SlideContent {
  const definition = getLayout(slide.layout) as LayoutDefinition<typeof slide.layout>
  return (definition.toContent as (s: Slide) => SlideContent)(slide)
}

export function createSlide<L extends SlideLayout>(layout: L, content?: Partial<SlideContent>): SlideOf<L> {
  const definition = getLayout(layout)
  const fields = definition.fromContent({ title: '', items: [], ...content })
  return { ...fields, id: createId(), layout, notes: '' } as unknown as SlideOf<L>
}

export function convertSlide(slide: Slide, layout: SlideLayout): Slide {
  if (slide.layout === layout) return slide
  const content = extractContent(slide)
  const definition = getLayout(layout)
  const fields = definition.fromContent(content)
  return { ...fields, id: slide.id, layout, notes: slide.notes ?? '' } as unknown as Slide
}

export function updateSlide(presentation: Presentation, id: string, patch: Partial<Slide>): Presentation {
  return {
    ...presentation,
    slides: presentation.slides.map((s) => (s.id === id ? ({ ...s, ...patch, id: s.id, layout: s.layout } as Slide) : s)),
  }
}

export function replaceSlide(presentation: Presentation, slide: Slide): Presentation {
  return { ...presentation, slides: presentation.slides.map((s) => (s.id === slide.id ? slide : s)) }
}

export function insertSlide(presentation: Presentation, slide: Slide, index: number): Presentation {
  const slides = [...presentation.slides]
  slides.splice(clamp(index, 0, slides.length), 0, slide)
  return { ...presentation, slides }
}

export function removeSlide(presentation: Presentation, id: string): Presentation {
  if (presentation.slides.length <= 1) return presentation
  return { ...presentation, slides: presentation.slides.filter((s) => s.id !== id) }
}

export function duplicateSlide(presentation: Presentation, id: string): { presentation: Presentation; newId: string | null } {
  const index = presentation.slides.findIndex((s) => s.id === id)
  if (index === -1) return { presentation, newId: null }
  const original = presentation.slides[index]
  const copy = structuredClone(original)
  copy.id = createId()
  return { presentation: insertSlide(presentation, copy, index + 1), newId: copy.id }
}

export function moveSlide(presentation: Presentation, fromIndex: number, toIndex: number): Presentation {
  const slides = [...presentation.slides]
  if (fromIndex < 0 || fromIndex >= slides.length) return presentation
  const [moved] = slides.splice(fromIndex, 1)
  slides.splice(clamp(toIndex, 0, slides.length), 0, moved)
  return { ...presentation, slides }
}

/**
 * Делит перегруженный слайд на два: вторая половина пунктов (или абзацев)
 * переносится на новый слайд того же макета сразу после текущего.
 */
export function splitSlide(presentation: Presentation, id: string): { presentation: Presentation; newId: string | null } {
  const index = presentation.slides.findIndex((s) => s.id === id)
  if (index === -1) return { presentation, newId: null }
  const slide = presentation.slides[index]
  const continuationTitle = slide.title.trim() ? `${slide.title.replace(/\s*\(продолжение\)$/, '')} (продолжение)` : ''

  let first: Slide | null = null
  let second: Slide | null = null
  if (slide.layout === 'bullets' && slide.bullets.length > 1) {
    const [a, b] = splitInHalf(slide.bullets)
    first = { ...slide, bullets: a }
    second = { ...slide, id: createId(), title: continuationTitle, bullets: b, notes: '' }
  } else if (slide.layout === 'text') {
    const paragraphs = paragraphsOf(slide.body)
    if (paragraphs.length > 1) {
      const [a, b] = splitInHalf(paragraphs)
      first = { ...slide, body: a.join('\n') }
      second = { ...slide, id: createId(), title: continuationTitle, body: b.join('\n'), notes: '' }
    }
  } else if (slide.layout === 'two-column' && (slide.left.length > 1 || slide.right.length > 1)) {
    const [l1, l2] = splitInHalf(slide.left)
    const [r1, r2] = splitInHalf(slide.right)
    first = { ...slide, left: l1, right: r1 }
    second = { ...slide, id: createId(), title: continuationTitle, left: l2, right: r2, notes: '' }
  }
  if (!first || !second) return { presentation, newId: null }
  const slides = [...presentation.slides]
  slides.splice(index, 1, first, second)
  return { presentation: { ...presentation, slides }, newId: second.id }
}

export function canSplitSlide(slide: Slide): boolean {
  switch (slide.layout) {
    case 'bullets':
      return slide.bullets.length > 1
    case 'text':
      return paragraphsOf(slide.body).length > 1
    case 'two-column':
      return slide.left.length > 1 || slide.right.length > 1
    default:
      return false
  }
}

/** Приводит ответ API к внутреннему формату: id у каждого слайда, уникальность id, обрезка пробелов. */
export function normalizeGenerated(response: GenerateResponse): Presentation {
  const seen = new Set<string>()
  const slides = response.slides.map((raw) => {
    let id = raw.id?.trim() || createId()
    if (seen.has(id)) id = createId()
    seen.add(id)
    return { ...raw, id, notes: raw.notes ?? '' } as Slide
  })
  return { title: response.title.trim(), slides }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}
