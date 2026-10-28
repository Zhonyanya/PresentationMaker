import type { Slide, SlideLayout, SlideOf } from '@/domain/presentation'
import type { PresentationTheme } from '@/theme/presentation-theme'
import type { AnyLayoutDefinition, LayoutDefinition, RenderContext } from './types'
import type { SlideScene } from './scene'
import { titleLayout } from './definitions/title'
import { textLayout } from './definitions/text'
import { bulletsLayout } from './definitions/bullets'
import { twoColumnLayout } from './definitions/two-column'
import { sectionLayout } from './definitions/section'
import { closingLayout } from './definitions/closing'

/**
 * Реестр макетов. Порядок здесь = порядок в меню выбора макета.
 * Новый макет: схема в src/domain/presentation.ts + файл в ./definitions + строка здесь.
 */
export const layoutRegistry: { [L in SlideLayout]: LayoutDefinition<L> } = {
  title: titleLayout,
  text: textLayout,
  bullets: bulletsLayout,
  'two-column': twoColumnLayout,
  section: sectionLayout,
  closing: closingLayout,
}

export const layoutList: AnyLayoutDefinition[] = Object.values(layoutRegistry)

export function getLayout<L extends SlideLayout>(layout: L): LayoutDefinition<L> {
  return layoutRegistry[layout]
}

export function buildSlideScene(slide: Slide, ctx: RenderContext): SlideScene {
  const definition = getLayout(slide.layout) as LayoutDefinition<typeof slide.layout>
  return (definition.buildScene as (s: SlideOf<typeof slide.layout>, c: RenderContext) => SlideScene)(slide, ctx)
}

/** Контекст рендера для каждого слайда: номер, общий счётчик, номер раздела. */
export function buildRenderContexts(slides: Slide[], theme: PresentationTheme): RenderContext[] {
  let section = 0
  return slides.map((slide, index) => {
    if (slide.layout === 'section') section += 1
    return { theme, number: index + 1, total: slides.length, sectionNumber: Math.max(section, 1) }
  })
}

export function buildPresentationScenes(slides: Slide[], theme: PresentationTheme): SlideScene[] {
  const contexts = buildRenderContexts(slides, theme)
  return slides.map((slide, i) => buildSlideScene(slide, contexts[i]))
}
