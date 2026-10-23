import { useMemo } from 'react'
import type { Slide } from '@/domain/presentation'
import { buildRenderContexts, buildSlideScene } from '@/layouts/registry'
import type { SlideScene } from '@/layouts/scene'
import { presentationTheme } from '@/theme/presentation-theme'

/**
 * Сцены всех слайдов. Кэш по объекту слайда: при правке одного слайда
 * остальные сцены (и миниатюры) не пересчитываются и не перерисовываются.
 */
const cache = new WeakMap<Slide, { key: string; scene: SlideScene }>()

export function usePresentationScenes(slides: Slide[]): SlideScene[] {
  return useMemo(() => {
    const contexts = buildRenderContexts(slides, presentationTheme)
    return slides.map((slide, i) => {
      const ctx = contexts[i]
      const key = `${ctx.number}/${ctx.total}/${ctx.sectionNumber}`
      const cached = cache.get(slide)
      if (cached && cached.key === key) return cached.scene
      const scene = buildSlideScene(slide, ctx)
      cache.set(slide, { key, scene })
      return scene
    })
  }, [slides])
}

export function sceneHasOverflow(scene: SlideScene): boolean {
  return scene.elements.some((e) => e.type === 'text' && e.overflow)
}
