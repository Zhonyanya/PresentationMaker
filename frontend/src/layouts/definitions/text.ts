import { AlignLeft } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentBox, contentChrome, fittedText, lines } from '../chrome'
import { nonEmpty, paragraphsOf } from '../content-utils'
import { comparisonContext, comparisonTableStyle, isComparisonTable, sourceImageBox, sourceTable } from '../source-material'
import { buildComposition, compositionAsText } from '../compositions'
import { textComposition } from '../text-compositions'
import { estimateTextHeight } from '../text-fit'

export const textLayout: LayoutDefinition<'text'> = {
  layout: 'text',
  label: 'Текст',
  description: 'Заголовок и один-два абзаца',
  icon: AlignLeft,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Заголовок', placeholder: 'Заголовок слайда', maxLength: 200 },
    { kind: 'textarea', key: 'body', label: 'Текст', placeholder: 'Основной текст слайда', maxLength: 4000, hint: 'Новая строка — новый абзац' },
  ],
  fromContent: (content) => {
    const items = content.columns
      ? [...content.columns.left.items, ...content.columns.right.items]
      : content.items
    return { title: content.title, body: nonEmpty(items.length ? items : [content.subtitle ?? '']).join('\n') }
  },
  toContent: (slide) => ({
    title: slide.title,
    items: [
      ...(slide.composition ? compositionAsText(slide.composition) : []),
      ...paragraphsOf(slide.body),
    ],
  }),
  buildScene: (slide, ctx) => {
    const { colors, typography, fonts } = ctx.theme
    const material = slide.sourceMaterial
    if (!material && slide.composition) return buildComposition(slide, slide.composition, ctx)
    if (material) {
      const box = contentBox(ctx)
      const isComparison = material.kind === 'table' && isComparisonTable(material)
      const context = isComparison ? comparisonContext(slide.body, material.rows) : lines(slide.body)
      const textSize = { max: 17, min: 13 }
      const textSpacing = { lineSpacing: 1, paragraphSpacing: 0 }
      const chrome = contentChrome(slide.title || (material.page ? `Страница ${material.page}` : 'Материал доклада'), ctx)
      const textStyle = {
        fontFace: fonts.body, color: colors.text, align: 'left' as const,
        valign: 'top' as const, ...textSpacing,
      }
      if (material.kind === 'image' && context.length) {
        const fullImage = sourceImageBox(material.png, box)
        if (fullImage.w / fullImage.h <= 1.18) {
          const imageWidth = Math.min(box.w * 0.44, Math.max(box.w * 0.32, fullImage.w))
          const copy = fittedText({
            field: 'body',
            box: { ...box, w: box.w - imageWidth - ctx.theme.spacing.columnGap },
            paragraphs: context,
            size: typography.body,
            style: { ...textStyle, lineSpacing: typography.lineSpacing, paragraphSpacing: typography.paragraphSpacing },
          })
          if (!copy.overflow) {
            const frame = { ...box, x: box.x + box.w - imageWidth, w: imageWidth }
            return {
              background: colors.background,
              elements: [...chrome, copy, { type: 'image', box: sourceImageBox(material.png, frame), src: material.png }],
            }
          }
        }
      }
      const contextHeight = context.length
        ? Math.min(box.h * 0.4, estimateTextHeight(context, box.w, textSize.max, textSpacing) / 0.96 + 0.16)
        : 0
      const visualBox = { ...box, y: box.y + contextHeight, h: box.h - contextHeight }
      return {
        background: colors.background,
        elements: [
          ...chrome,
          ...(context.length ? [fittedText({
            field: 'body',
            floor: material.kind === 'table' ? typography.absoluteMinFontSize : undefined,
            box: { ...box, h: contextHeight - 0.1 },
            paragraphs: context,
            size: textSize,
            style: textStyle,
          })] : []),
          material.kind === 'table'
            ? sourceTable(material.rows, visualBox, fonts.body, typography.absoluteMinFontSize,
              material.merges, isComparison ? comparisonTableStyle(ctx.theme) : undefined)
            : { type: 'image', box: sourceImageBox(material.png, visualBox), src: material.png },
        ],
      }
    }
    return {
      background: colors.background,
      elements: [
        ...contentChrome(slide.title, ctx),
        ...(textComposition(slide, ctx) ?? [fittedText({
          field: 'body',
          floor: typography.absoluteMinFontSize,
          box: contentBox(ctx),
          paragraphs: lines(slide.body),
          size: typography.body,
          placeholder: 'Основной текст слайда',
          style: {
            fontFace: fonts.body,
            color: colors.text,
            align: 'left',
            valign: 'top',
            lineSpacing: typography.lineSpacing + 0.1,
            paragraphSpacing: typography.paragraphSpacing + 2,
          },
        })]),
      ],
    }
  },
}
