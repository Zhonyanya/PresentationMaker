import type { Slide } from '@/domain/presentation'
import type { PresentationTheme } from '@/theme/presentation-theme'
import { buildPresentationScenes } from './registry'
import type { Box, SceneElement, SceneText } from './scene'
import { isEmptyText } from './scene'
import { estimateTextHeight } from './text-fit'

const tolerance = 0.01

type VisibleElement = Exclude<SceneElement, { type: 'rect' }>

type ElementLocation = {
  type: VisibleElement['type']
  element: number
  field?: string
}

type LayoutWarning = { code: 'empty-content' } | (ElementLocation & (
  | { code: 'estimated-text-clipping' | 'reduced-text-size'; fontSize: number }
  | { code: 'outside-slide' | 'outside-content-band' }
  | { code: 'overlapping-content'; with: ElementLocation }
))

function location(element: VisibleElement, index: number): ElementLocation {
  return {
    element: index + 1,
    type: element.type,
    ...(element.type === 'text' && { field: element.field }),
  }
}

function textHeight(element: SceneText) {
  return estimateTextHeight(element.paragraphs, element.box.w, element.style.fontSize, element.style)
}

function paintedBox(element: VisibleElement): Box {
  const { box } = element
  if (element.type !== 'text') return box
  const h = Math.min(box.h, textHeight(element))
  const offset = { top: 0, middle: (box.h - h) / 2, bottom: box.h - h }[element.style.valign]
  return { ...box, y: box.y + offset, h }
}

function overlaps(first: Box, second: Box) {
  return Math.min(first.x + first.w, second.x + second.w) - Math.max(first.x, second.x) > tolerance
    && Math.min(first.y + first.h, second.y + second.h) - Math.max(first.y, second.y) > tolerance
}

function verticalCoverage(boxes: Box[], start: number, end: number) {
  let occupied = 0
  let previousEnd = start
  for (const box of [...boxes].sort((first, second) => first.y - second.y)) {
    const rangeStart = Math.max(previousEnd, box.y)
    const rangeEnd = Math.min(end, box.y + box.h)
    if (rangeEnd > rangeStart) {
      occupied += rangeEnd - rangeStart
      previousEnd = rangeEnd
    }
  }
  return Math.round(1000 * occupied / (end - start)) / 1000
}

export function auditPresentation(slides: Slide[], theme: PresentationTheme) {
  return buildPresentationScenes(slides, theme).map((scene, index) => {
    const slide = slides[index]
    const warnings: LayoutWarning[] = []
    const contents: { where: ElementLocation; bounds: Box; fontSize?: number }[] = []
    const { contentTop, contentBottom } = theme.spacing
    const hasContentBand = slide.layout === 'text' || slide.layout === 'bullets' || slide.layout === 'two-column'

    scene.elements.forEach((element, elementIndex) => {
      if (element.type === 'rect' || (element.type === 'text' && isEmptyText(element))) return
      const where = location(element, elementIndex)
      const box = element.box
      if (box.x < -tolerance || box.y < -tolerance ||
          box.x + box.w > theme.slide.width + tolerance || box.y + box.h > theme.slide.height + tolerance) {
        warnings.push({ code: 'outside-slide', ...where })
      }
      if (element.type === 'text' && element.overflow) {
        const code = textHeight(element) > box.h + tolerance ? 'estimated-text-clipping' : 'reduced-text-size'
        warnings.push({ code, ...where, fontSize: element.style.fontSize })
      }
      if (!hasContentBand || box.y < contentTop - tolerance || box.y >= contentBottom) return
      if (box.y + box.h > contentBottom + tolerance) {
        warnings.push({ code: 'outside-content-band', ...where })
      }
      const bounds = paintedBox(element)
      for (const other of contents) {
        if (overlaps(bounds, other.bounds)) {
          warnings.push({ code: 'overlapping-content', ...where, with: other.where })
        }
      }
      const fontSize = element.type === 'text' ? element.style.fontSize
        : element.type === 'chart' ? element.labelSize
          : element.type === 'table' ? element.fontSize : undefined
      contents.push({ where, bounds, fontSize })
    })

    if (hasContentBand && !contents.length) warnings.push({ code: 'empty-content' })
    const sizes = contents.flatMap(({ fontSize }) => fontSize === undefined ? [] : [fontSize])
    return {
      number: index + 1,
      layout: slide.layout,
      contentVerticalCoverage: hasContentBand
        ? verticalCoverage(contents.map(({ bounds }) => bounds), contentTop, contentBottom) : null,
      minimumContentFontSize: sizes.length ? Math.min(...sizes) : null,
      contentTypes: [...new Set(contents.map(({ where }) => where.type))],
      warnings,
    }
  })
}
