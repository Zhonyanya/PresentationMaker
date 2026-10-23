import { Rows2 } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import { contentWidth, fittedText, lines, logoElement } from '../chrome'

export const sectionLayout: LayoutDefinition<'section'> = {
  layout: 'section',
  label: 'Раздел',
  description: 'Разделитель между частями доклада',
  icon: Rows2,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Название раздела', placeholder: 'Название раздела', maxLength: 200 },
    { kind: 'textarea', key: 'subtitle', label: 'Пояснение', placeholder: 'О чём этот раздел', optional: true, maxLength: 400 },
  ],
  fromContent: (content) => ({ title: content.title, subtitle: content.subtitle ?? content.items[0] ?? '' }),
  toContent: (slide) => ({ title: slide.title, subtitle: slide.subtitle, items: [] }),
  buildScene: (slide, ctx) => {
    const { colors, spacing, typography, fonts, slide: size } = ctx.theme
    const width = contentWidth(ctx)
    const base = { fontFace: fonts.body, align: 'left' as const, lineSpacing: 1.05, paragraphSpacing: 0 }
    return {
      background: colors.surface,
      elements: [
        { type: 'rect', fill: colors.primary, box: { x: 0, y: 0, w: 0.2, h: size.height } },
        fittedText({
          field: 'number',
          box: { x: spacing.marginX, y: 1.75, w: 3, h: 1.1 },
          paragraphs: [{ text: String(ctx.sectionNumber).padStart(2, '0') }],
          size: typography.sectionNumber,
          style: { ...base, fontFace: fonts.heading, color: colors.accent, bold: true, valign: 'bottom', lineSpacing: 1 },
        }),
        fittedText({
          field: 'title',
          box: { x: spacing.marginX, y: 3.05, w: width, h: 2.0 },
          paragraphs: lines(slide.title),
          size: typography.sectionTitle,
          placeholder: 'Название раздела',
          style: { ...base, fontFace: fonts.heading, color: colors.primary, bold: true, valign: 'top', lineSpacing: 1 },
        }),
        fittedText({
          field: 'subtitle',
          box: { x: spacing.marginX, y: 5.2, w: width, h: 1.2 },
          paragraphs: lines(slide.subtitle),
          size: typography.coverSubtitle,
          placeholder: 'Пояснение',
          style: { ...base, color: colors.textMuted, valign: 'top' },
        }),
        ...logoElement(ctx, false),
      ],
    }
  },
}
