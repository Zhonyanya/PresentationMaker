import { useMemo } from 'react'
import type { Slide } from '@/domain/presentation'
import { buildRenderContexts, buildSlideScene } from '@/layouts/registry'
import type { SlideScene } from '@/layouts/scene'
import type { ThemeId } from '@/theme/presentation-theme'
import { resolvePresentationTheme } from '@/theme/theme-presets'

/**
 * Сцены всех слайдов. Кэш пересчитывает сцену, когда меняется слайд
 * или его положение и оформление среди соседей.
 */
const cache = new WeakMap<Slide, { key: string; scene: SlideScene }>()

export function usePresentationScenes(slides: Slide[], themeId?: ThemeId): SlideScene[] {
  const theme = resolvePresentationTheme(themeId)
  return useMemo(() => {
    const contexts = buildRenderContexts(slides, theme)
    return slides.map((slide, i) => {
      const ctx = contexts[i]
      const key = `${theme.id}/${ctx.number}/${ctx.total}/${ctx.sectionNumber}/${ctx.leadPlacement}`
      const cached = cache.get(slide)
      if (cached && cached.key === key) return cached.scene
      const scene = buildSlideScene(slide, ctx)
      cache.set(slide, { key, scene })
      return scene
    })
  }, [slides, theme])
}

export function sceneHasOverflow(scene: SlideScene, themeId?: ThemeId): boolean {
  return scene.elements.some((element) => {
    if (element.type === 'text') return element.overflow
    return element.type === 'table'
      && element.box.y + element.box.h > resolvePresentationTheme(themeId).spacing.contentBottom + 0.01
  })
}
