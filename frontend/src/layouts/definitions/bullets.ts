import { List } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { bullets, contentBox, contentChrome, fittedText } from '../chrome'
import { nonEmpty } from '../content-utils'

export const bulletsLayout: LayoutDefinition<'bullets'> = {
  layout: 'bullets',
  label: 'Список',
  description: 'Заголовок и маркированный список',
  icon: List,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Заголовок', placeholder: 'Заголовок слайда', maxLength: 200 },
    { kind: 'list', key: 'bullets', label: 'Пункты списка', placeholder: 'Текст пункта', addLabel: 'Добавить пункт' },
  ],
  fromContent: (content) => ({
    title: content.title,
    bullets: content.columns
      ? nonEmpty([...content.columns.left.items, ...content.columns.right.items])
      : nonEmpty(content.items.length ? content.items : [content.subtitle ?? '']),
  }),
  toContent: (slide) => ({ title: slide.title, items: slide.bullets }),
  buildScene: (slide, ctx) => {
    const { colors, typography, fonts } = ctx.theme
    return {
      background: colors.background,
      elements: [
        ...contentChrome(slide.title, ctx),
        fittedText({
          field: 'bullets',
          floor: typography.absoluteMinFontSize,
          box: contentBox(ctx),
          paragraphs: bullets(slide.bullets),
          size: typography.bullets,
          placeholder: 'Добавьте пункты списка',
          style: {
            fontFace: fonts.body,
            color: colors.text,
            align: 'left',
            valign: 'top',
            lineSpacing: typography.lineSpacing,
            paragraphSpacing: typography.paragraphSpacing,
            bulletIndent: typography.bulletIndent,
          },
        }),
      ],
    }
  },
}
