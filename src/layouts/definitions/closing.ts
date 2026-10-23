import { Flag } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentWidth, fittedText, lines, logoElement } from '../chrome'

export const closingLayout: LayoutDefinition<'closing'> = {
  layout: 'closing',
  label: 'Заключительный',
  description: 'Благодарность, контакты, вопросы',
  icon: Flag,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Заголовок', placeholder: 'Спасибо за внимание', maxLength: 200 },
    { kind: 'textarea', key: 'subtitle', label: 'Дополнительный текст', placeholder: 'Контакты докладчика или приглашение к вопросам', optional: true, maxLength: 400 },
  ],
  fromContent: (content) => ({ title: content.title, subtitle: content.subtitle ?? content.items[0] ?? '' }),
  toContent: (slide) => ({ title: slide.title, subtitle: slide.subtitle, items: [] }),
  buildScene: (slide, ctx) => {
    const { colors, spacing, typography, fonts, slide: size } = ctx.theme
    const width = Math.min(contentWidth(ctx), 10.8)
    const base = { fontFace: fonts.body, align: 'left' as const, lineSpacing: 1.05, paragraphSpacing: 0 }
    return {
      background: colors.primary,
      elements: [
        { type: 'rect', fill: colors.accentOnPrimary, box: { x: spacing.marginX, y: 2.35, w: 0.9, h: 0.07 } },
        fittedText({
          field: 'title',
          box: { x: spacing.marginX, y: 2.6, w: width, h: 1.8 },
          paragraphs: lines(slide.title),
          size: typography.coverTitle,
          placeholder: 'Спасибо за внимание',
          style: { ...base, fontFace: fonts.heading, color: colors.textOnPrimary, bold: true, valign: 'top', lineSpacing: 1 },
        }),
        fittedText({
          field: 'subtitle',
          box: { x: spacing.marginX, y: 4.6, w: width, h: 1.4 },
          paragraphs: lines(slide.subtitle),
          size: typography.coverSubtitle,
          placeholder: 'Дополнительный текст',
          style: { ...base, color: colors.textOnPrimaryMuted, valign: 'top' },
        }),
        { type: 'rect', fill: colors.accent, box: { x: 0, y: size.height - 0.12, w: size.width, h: 0.12 } },
        ...logoElement(ctx, true),
      ],
    }
  },
}
