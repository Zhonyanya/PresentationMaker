import { generateMockPresentation } from '@/api/mock/mock-generator'
import { normalizeGenerated } from '@/domain/operations'
import { demoExamples, type DemoExample } from '@/data/demo-examples'
import { buildPresentationScenes } from '@/layouts/registry'
import type { SlideScene } from '@/layouts/scene'
import type { Slide } from '@/domain/presentation'
import { presentationTheme } from '@/theme/presentation-theme'

/**
 * Витрина на главном экране: настоящие слайды, построенные из демо-примеров
 * тем же генератором и рендерером, что и в редакторе. Считается один раз.
 */
function build(example: DemoExample) {
  const presentation = normalizeGenerated(
    generateMockPresentation({ text: example.text, title: example.title || undefined, slideCount: example.slideCount }),
  )
  return { presentation, scenes: buildPresentationScenes(presentation.slides, presentationTheme) }
}

interface Showcase {
  title: string
  slideCount: number
  gallery: SlideScene[]
  /** Слайды витрины — в том же порядке, что и gallery (для подписей) */
  gallerySlides: Slide[]
  previews: Record<string, SlideScene>
}

let cache: Showcase | null = null

export function getShowcase(): Showcase {
  if (cache) return cache
  const main = build(demoExamples[0])
  cache = {
    title: main.presentation.title,
    slideCount: main.presentation.slides.length,
    // Без заключительного слайда — он повторяет титульный по цвету
    gallery: main.scenes.slice(0, -1),
    gallerySlides: main.presentation.slides.slice(0, -1),
    previews: Object.fromEntries(demoExamples.map((example) => [example.id, build(example).scenes[1]])),
  }
  return cache
}
