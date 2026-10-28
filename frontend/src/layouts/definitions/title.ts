import { Presentation } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentWidth, fittedText, lines, logoElement } from '../chrome'

export const titleLayout: LayoutDefinition<'title'> = {
  layout: 'title',
  label: 'Титульный',
  description: 'Название, подзаголовок и подпись',
  icon: Presentation,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Название', placeholder: 'Название презентации', maxLength: 200 },
    { kind: 'textarea', key: 'subtitle', label: 'Подзаголовок', placeholder: 'Тема доклада или мероприятие', optional: true, maxLength: 400 },
    { kind: 'text', key: 'caption', label: 'Подпись', placeholder: 'Например: Москва · 2026', optional: true, maxLength: 200, hint: 'Город, дата или докладчик' },
  ],
  fromContent: (content) => ({
    title: content.title,
    subtitle: content.subtitle ?? content.items[0] ?? '',
    caption: '',
  }),
  toContent: (slide) => ({ title: slide.title, subtitle: slide.subtitle, items: [] }),
  buildScene: (slide, ctx) => {
    const { colors, spacing, typography, fonts, slide: size } = ctx.theme
    const width = Math.min(contentWidth(ctx), 10.8)
    const base = { fontFace: fonts.body, align: 'left' as const, lineSpacing: 1.05, paragraphSpacing: 0 }
    return {
      background: colors.primary,
      elements: [
        { type: 'rect', fill: colors.accentOnPrimary, box: { x: spacing.marginX, y: 2.0, w: 0.9, h: 0.07 } },
        fittedText({
          field: 'title',
          box: { x: spacing.marginX, y: 2.25, w: width, h: 2.35 },
          paragraphs: lines(slide.title),
          size: typography.coverTitle,
          placeholder: 'Название презентации',
          style: { ...base, fontFace: fonts.heading, color: colors.textOnPrimary, bold: true, valign: 'bottom', lineSpacing: 1 },
        }),
        fittedText({
          field: 'subtitle',
          box: { x: spacing.marginX, y: 4.8, w: width, h: 1.15 },
          paragraphs: lines(slide.subtitle),
          size: typography.coverSubtitle,
          placeholder: 'Подзаголовок',
          style: { ...base, color: colors.textOnPrimaryMuted, valign: 'top' },
        }),
        fittedText({
          field: 'caption',
          box: { x: spacing.marginX, y: 6.45, w: width, h: 0.42 },
          paragraphs: lines(slide.caption),
          size: { max: typography.caption, min: 10 },
          placeholder: 'Подпись',
          style: { ...base, color: colors.textOnPrimaryMuted, valign: 'top' },
        }),
        { type: 'rect', fill: colors.accent, box: { x: 0, y: size.height - 0.12, w: size.width, h: 0.12 } },
        ...logoElement(ctx, true),
      ],
    }
  },
}
