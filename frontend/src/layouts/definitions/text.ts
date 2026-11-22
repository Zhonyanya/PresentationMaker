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
      let contextHeight = 0
      if (context.length) {
        contextHeight = material.kind === 'image' ? (context.length > 1 ? 1 : 0.68)
          : Math.min(box.h * 0.4, estimateTextHeight(context, box.w, textSize.max, textSpacing) / 0.96 + 0.16)
      }
      const visualBox = { ...box, y: box.y + contextHeight, h: box.h - contextHeight }
      return {
        background: colors.background,
        elements: [
          ...contentChrome(slide.title || (material.page ? `Страница ${material.page}` : 'Материал доклада'), ctx),
          ...(context.length ? [fittedText({
            field: 'body',
            floor: material.kind === 'table' ? typography.absoluteMinFontSize : undefined,
            box: { ...box, h: contextHeight - 0.1 },
            paragraphs: context,
            size: textSize,
            style: {
              fontFace: fonts.body, color: colors.text, align: 'left',
              valign: 'top', ...textSpacing,
            },
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
