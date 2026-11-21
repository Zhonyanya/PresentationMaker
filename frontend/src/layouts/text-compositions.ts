import type { TextSlide } from '@/domain/presentation'
import { contentBox, fittedText, lines } from './chrome'
import type { Box, SceneElement, SceneParagraph, SceneText } from './scene'
import type { RenderContext } from './types'

const sentences = new Intl.Segmenter('ru', { granularity: 'sentence' })

export function textComposition(slide: TextSlide, ctx: RenderContext): SceneElement[] | undefined {
  const paragraphs = lines(slide.body)
  if (!paragraphs.length) return undefined
  const { colors, typography, fonts } = ctx.theme
  const box = contentBox(ctx)
  const padding = 0.26
  const gap = 0.18
  const texts: SceneText[] = []
  const backgrounds: SceneElement[] = []
  const text = (content: SceneParagraph[], bounds: Box, options: {
    accent?: boolean; max?: number; field?: 'body' | 'stepNumber'
  } = {}) => {
    const { accent = false, max = typography.body.max, field = 'body' } = options
    texts.push(fittedText({
      field, box: bounds, paragraphs: content, size: { max, min: 16 },
      style: {
        fontFace: accent ? fonts.heading : fonts.body,
        color: accent ? colors.textOnPrimary : colors.text,
        bold: accent, align: field === 'stepNumber' ? 'center' : 'left',
        valign: 'middle', lineSpacing: 1.04, paragraphSpacing: typography.paragraphSpacing,
      },
    }))
  }
  const surface = (bounds: Box, fill = colors.surface) =>
    backgrounds.push({ type: 'rect', box: bounds, fill })
  const inset = (bounds: Box): Box => ({
    x: bounds.x + padding, y: bounds.y + padding,
    w: bounds.w - 2 * padding, h: bounds.h - 2 * padding,
  })
  switch (slide.textStyle) {
    case 'blocks': {
      if (paragraphs.length < 2 || paragraphs.length > 3) return undefined
      const width = (box.w - (paragraphs.length - 1) * gap) / paragraphs.length
      paragraphs.forEach((paragraph, index) => {
        const card = { ...box, x: box.x + index * (width + gap), w: width, h: box.h * 0.72 }
        surface(card)
        surface({ ...card, h: 0.06 }, colors.accent)
        text([paragraph], inset(card))
      })
      break
    }
    case 'steps': {
      if (paragraphs.length < 2 || paragraphs.length > 4
          || paragraphs.some(({ text }) => /^\d+[.)]\s/.test(text))) return undefined
      const height = (box.h - (paragraphs.length - 1) * gap) / paragraphs.length
      paragraphs.forEach((paragraph, index) => {
        const row = { ...box, y: box.y + index * (height + gap), h: height }
        const numberBox = { ...row, w: 0.64 }
        surface(row)
        surface(numberBox, colors.primary)
        text([{ text: String(index + 1) }], numberBox, { accent: true, field: 'stepNumber' })
        text([paragraph], inset({ ...row, x: row.x + 0.64, w: row.w - 0.64 }))
      })
      break
    }
    case 'lead':
    default: {
      const [first, ...rest] = paragraphs
      const firstSentence = sentences.segment(first.text).containing(0)?.segment.trim() ?? first.text
      const lead = slide.textStyle === 'lead' ? first.text : firstSentence
      const remainingFirst = first.text.slice(lead.length).trim()
      const details = remainingFirst ? [{ text: remainingFirst }, ...rest] : rest
      if (lead.length > 185 || details.length > 4) return undefined
      if (ctx.sideLead && lead.length <= 110 && details.length
          && details.reduce((sum, item) => sum + item.text.length, 0) <= 320) {
        const highlight = { ...box, w: box.w * 0.40, h: box.h * 0.87 }
        surface(highlight, colors.primary)
        text([{ text: lead }], inset(highlight), { accent: true, max: 26 })
        text(details, inset({ ...box, x: box.x + highlight.w + gap, w: box.w - highlight.w - gap }))
        break
      }
      const highlight = { ...box, h: details.length ? box.h * 0.4 : box.h * 0.58 }
      surface(highlight, colors.primary)
      text([{ text: lead }], inset(highlight), { accent: true, max: Math.max(26, typography.heading.max) })
      if (details.length) {
        text(details, {
          x: box.x + padding, y: box.y + highlight.h + gap,
          w: box.w - 2 * padding, h: box.h - highlight.h - gap,
        })
      }
    }
  }
  return texts.some((element) => element.overflow) ? undefined : [...backgrounds, ...texts]
}
