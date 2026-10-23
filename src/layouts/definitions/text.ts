import { AlignLeft } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentBox, contentChrome, fittedText, lines } from '../chrome'
import { nonEmpty, paragraphsOf } from '../content-utils'

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
