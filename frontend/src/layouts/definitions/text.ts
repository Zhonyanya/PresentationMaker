import { AlignLeft } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentBox, contentChrome, fittedText, lines } from '../chrome'
import { nonEmpty, paragraphsOf } from '../content-utils'
import { sourceImageBox, sourceTable } from '../source-material'

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
  toContent: (slide) => ({ title: slide.title, items: paragraphsOf(slide.body) }),
  buildScene: (slide, ctx) => {
    const { colors, typography, fonts } = ctx.theme
    const material = slide.sourceMaterial
    if (material) {
      const box = contentBox(ctx)
      const context = material.kind === 'image' ? lines(slide.body) : []
      const contextHeight = context.length ? 0.68 : 0
      const imageBox = { ...box, y: box.y + contextHeight, h: box.h - contextHeight }
      return {
        background: colors.background,
        elements: [
          ...contentChrome(slide.title || (material.page ? `Страница ${material.page}` : 'Материал доклада'), ctx),
          ...(context.length ? [fittedText({
            field: 'body',
            box: { ...box, h: contextHeight - 0.1 },
            paragraphs: context,
            size: { max: 17, min: 13 },
            style: {
              fontFace: fonts.body, color: colors.text, align: 'left',
              valign: 'top', lineSpacing: 1, paragraphSpacing: 0,
            },
          })] : []),
          material.kind === 'table'
            ? sourceTable(material.rows, box, fonts.body, typography.absoluteMinFontSize)
            : { type: 'image', box: sourceImageBox(material.png, imageBox), src: material.png },
        ],
      }
    }
    return {
      background: colors.background,
      elements: [
        ...contentChrome(slide.title, ctx),
        fittedText({
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
        }),
      ],
    }
  },
}
