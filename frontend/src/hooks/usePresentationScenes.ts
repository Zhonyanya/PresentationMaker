import { useMemo } from 'react'
import type { Slide } from '@/domain/presentation'
import { buildRenderContexts, buildSlideScene } from '@/layouts/registry'
import type { SlideScene } from '@/layouts/scene'
import type { Brandbook } from '@/domain/brandbook'
import { themeFor, type PresentationTheme } from '@/theme/presentation-theme'

/**
 * Сцены всех слайдов. Кэш по объекту слайда: при правке одного слайда
 * остальные сцены (и миниатюры) не пересчитываются и не перерисовываются.
 */
const cache = new WeakMap<Slide, { key: string; theme: PresentationTheme; scene: SlideScene }>()

export function usePresentationScenes(slides: Slide[], brandbook?: Brandbook): SlideScene[] {
  const theme = useMemo(() => themeFor(brandbook), [brandbook])
  return useMemo(() => {
    const contexts = buildRenderContexts(slides, theme)
    return slides.map((slide, i) => {
      const ctx = contexts[i]
      const key = `${ctx.number}/${ctx.total}/${ctx.sectionNumber}`
      const cached = cache.get(slide)
      if (cached && cached.key === key && cached.theme === theme) return cached.scene
      const scene = buildSlideScene(slide, ctx)
      cache.set(slide, { key, theme, scene })
      return scene
    })
  }, [slides, theme])
}

export function sceneHasOverflow(scene: SlideScene): boolean {
  return scene.elements.some((e) => e.type === 'text' && e.overflow)
}
