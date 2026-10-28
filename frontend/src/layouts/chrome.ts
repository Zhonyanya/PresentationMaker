import type { RenderContext } from './types'
import type { Box, SceneElement, SceneParagraph, SceneText, TextStyle } from './scene'
import { fitText } from './text-fit'
import type { FontSizeRange } from '@/theme/presentation-theme'

/** Строит текстовый элемент с автоподбором размера шрифта. */
export function fittedText(params: {
  /** Аварийный минимум шрифта, pt (обычно theme.typography.absoluteMinFontSize) */
  floor?: number
  field: string
  box: Box
  paragraphs: SceneParagraph[]
  size: FontSizeRange | number
  style: Omit<TextStyle, 'fontSize'>
  placeholder?: string
}): SceneText {
  const range = typeof params.size === 'number' ? { max: params.size, min: params.size } : params.size
  const nonEmpty = params.paragraphs.filter((p) => p.text.trim() !== '')
  const measured = nonEmpty.length ? nonEmpty : [{ text: params.placeholder ?? '' }]
  const options = {
    bold: params.style.bold,
    lineSpacing: params.style.lineSpacing,
    paragraphSpacing: params.style.paragraphSpacing,
    bulletIndent: params.style.bulletIndent,
  }
  let fit = fitText(measured, params.box, { ...range, ...options })
  // Текста больше, чем помещается: уменьшаем ниже минимума, но не дальше аварийного порога.
  // overflow остаётся true — редактор предупредит пользователя.
  if (fit.overflow && params.floor !== undefined && params.floor < range.min) {
    const emergency = fitText(measured, params.box, { max: range.min - 0.5, min: params.floor, step: 0.5, ...options })
    fit = { ...emergency, overflow: true }
  }
  return {
    type: 'text',
    field: params.field,
    box: params.box,
    paragraphs: nonEmpty,
    style: { ...params.style, fontSize: fit.fontSize },
    placeholder: params.placeholder,
    overflow: nonEmpty.length > 0 && fit.overflow,
    shrunk: nonEmpty.length > 0 && fit.shrunk,
  }
}

export const lines = (text: string | undefined): SceneParagraph[] =>
  (text ?? '')
    .split(/\n+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => ({ text: t }))

export const bullets = (items: string[]): SceneParagraph[] =>
  items.map((t) => t.trim()).filter(Boolean).map((t) => ({ text: t, bullet: true }))

/** Ширина области контента с учётом полей */
export function contentWidth(ctx: RenderContext): number {
  return ctx.theme.slide.width - ctx.theme.spacing.marginX * 2
}

/** Логотип, если он задан в теме. */
export function logoElement(ctx: RenderContext, dark: boolean): SceneElement[] {
  const { logo, slide, spacing } = ctx.theme
  if (!logo) return []
  if (dark && !logo.onDarkSlides) return []
  return [
    {
      type: 'image',
      src: dark && logo.srcOnDark ? logo.srcOnDark : logo.src,
      box: { x: slide.width - spacing.marginX - logo.width, y: 0.45, w: logo.width, h: logo.height },
    },
  ]
}

/**
 * Общая «рамка» контентного слайда: акцентная линия, заголовок,
 * нижний колонтитул с номером, логотип.
 */
export function contentChrome(title: string, ctx: RenderContext): SceneElement[] {
  const { theme } = ctx
  const { colors, spacing, typography, fonts, slide, footer, logo } = theme
  const width = contentWidth(ctx)
  const logoSpace = logo ? logo.width + 0.4 : 0
  const footerY = spacing.contentBottom + 0.3

  const elements: SceneElement[] = [
    { type: 'rect', fill: colors.accent, box: { x: spacing.marginX, y: spacing.headingTop - 0.14, w: 0.55, h: 0.06 } },
    fittedText({
      field: 'title',
      floor: typography.absoluteMinFontSize + 5,
      box: { x: spacing.marginX, y: spacing.headingTop, w: width - logoSpace, h: spacing.headingHeight },
      paragraphs: lines(title).length ? [{ text: title.replace(/\n+/g, ' ').trim() }] : [],
      size: typography.heading,
      placeholder: 'Заголовок слайда',
      style: {
        fontFace: fonts.heading,
        color: colors.primary,
        bold: true,
        align: 'left',
        valign: 'top',
        lineSpacing: 1,
        paragraphSpacing: 0,
      },
    }),
    { type: 'rect', fill: colors.divider, box: { x: spacing.marginX, y: footerY, w: width, h: 0.01 } },
    ...logoElement(ctx, false),
  ]

  const footerBox = { y: footerY + 0.12, h: 0.32 }
  if (footer.text) {
    elements.push(
      fittedText({
        field: 'footer',
        box: { x: spacing.marginX, ...footerBox, w: width - 1.2 },
        paragraphs: [{ text: footer.text }],
        size: typography.footer,
        style: { fontFace: fonts.body, color: colors.textMuted, align: 'left', valign: 'top', lineSpacing: 1, paragraphSpacing: 0 },
      }),
    )
  }
  if (footer.showSlideNumber) {
    elements.push(
      fittedText({
        field: 'number',
        box: { x: slide.width - spacing.marginX - 1, ...footerBox, w: 1 },
        paragraphs: [{ text: String(ctx.number) }],
        size: typography.footer,
        style: { fontFace: fonts.body, color: colors.textMuted, align: 'right', valign: 'top', lineSpacing: 1, paragraphSpacing: 0 },
      }),
    )
  }
  return elements
}

export function contentBox(ctx: RenderContext): Box {
  const { spacing } = ctx.theme
  return {
    x: spacing.marginX,
    y: spacing.contentTop,
    w: contentWidth(ctx),
    h: spacing.contentBottom - spacing.contentTop,
  }
}
