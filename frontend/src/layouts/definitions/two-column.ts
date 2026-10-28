import { Columns2 } from 'lucide-react'
import type { LayoutDefinition } from '../types'
import type { SceneText } from '../scene'
import { bullets, contentBox, contentChrome, fittedText, lines } from '../chrome'
import { nonEmpty, splitInHalf } from '../content-utils'

export const twoColumnLayout: LayoutDefinition<'two-column'> = {
  layout: 'two-column',
  label: 'Две колонки',
  description: 'Сравнение или два направления',
  icon: Columns2,
  fields: [
    { kind: 'textarea', key: 'title', label: 'Заголовок', placeholder: 'Заголовок слайда', maxLength: 200 },
    { kind: 'text', key: 'leftTitle', label: 'Заголовок левой колонки', placeholder: 'Например: Было', optional: true, maxLength: 120 },
    { kind: 'list', key: 'left', label: 'Левая колонка', placeholder: 'Текст пункта', addLabel: 'Добавить пункт' },
    { kind: 'text', key: 'rightTitle', label: 'Заголовок правой колонки', placeholder: 'Например: Стало', optional: true, maxLength: 120 },
    { kind: 'list', key: 'right', label: 'Правая колонка', placeholder: 'Текст пункта', addLabel: 'Добавить пункт' },
  ],
  fromContent: (content) => {
    if (content.columns) {
      return {
        title: content.title,
        leftTitle: content.columns.left.title ?? '',
        left: nonEmpty(content.columns.left.items),
        rightTitle: content.columns.right.title ?? '',
        right: nonEmpty(content.columns.right.items),
      }
    }
    const [left, right] = splitInHalf(nonEmpty(content.items))
    return { title: content.title, leftTitle: '', left, rightTitle: '', right }
  },
  toContent: (slide) => ({
    title: slide.title,
    items: [...slide.left, ...slide.right],
    columns: {
      left: { title: slide.leftTitle, items: slide.left },
      right: { title: slide.rightTitle, items: slide.right },
    },
  }),
  buildScene: (slide, ctx) => {
    const { colors, typography, fonts, spacing } = ctx.theme
    const area = contentBox(ctx)
    const columnWidth = (area.w - spacing.columnGap) / 2
    const hasHeadings = Boolean(slide.leftTitle?.trim() || slide.rightTitle?.trim())
    const headingHeight = hasHeadings ? 0.5 : 0
    const bodyTop = area.y + (hasHeadings ? headingHeight + 0.2 : 0)
    const bodyHeight = area.y + area.h - bodyTop
    const columnX = [area.x, area.x + columnWidth + spacing.columnGap]

    const bodyStyle = {
      fontFace: fonts.body,
      color: colors.text,
      align: 'left' as const,
      valign: 'top' as const,
      lineSpacing: typography.lineSpacing,
      paragraphSpacing: typography.paragraphSpacing,
      bulletIndent: typography.bulletIndent,
    }
    const columns = (['left', 'right'] as const).map((side, i) =>
      fittedText({
        field: side,
          floor: typography.absoluteMinFontSize,
        box: { x: columnX[i], y: bodyTop, w: columnWidth, h: bodyHeight },
        paragraphs: bullets(slide[side]),
        size: { max: typography.bullets.max - 2, min: typography.bullets.min },
        placeholder: 'Добавьте пункты',
        style: bodyStyle,
      }),
    )
    // Обе колонки — одним размером шрифта
    const fontSize = Math.min(...columns.map((c) => c.style.fontSize))
    const unified: SceneText[] = columns.map((c) => ({
      ...c,
      style: { ...c.style, fontSize },
      shrunk: c.paragraphs.length > 0 && fontSize < typography.bullets.max - 2,
    }))

    const headings = hasHeadings
      ? (['leftTitle', 'rightTitle'] as const).map((key, i) =>
          fittedText({
            field: key,
            box: { x: columnX[i], y: area.y, w: columnWidth, h: headingHeight },
            paragraphs: lines(slide[key]),
            size: { max: typography.columnHeading, min: 12 },
            placeholder: 'Заголовок колонки',
            style: { ...bodyStyle, fontFace: fonts.heading, color: colors.accent, bold: true, valign: 'bottom', lineSpacing: 1 },
          }),
        )
      : []

    return {
      background: colors.background,
      elements: [
        ...contentChrome(slide.title, ctx),
        {
          type: 'rect',
          fill: colors.divider,
          box: { x: area.x + columnWidth + spacing.columnGap / 2 - 0.005, y: area.y, w: 0.01, h: area.h },
        },
        ...headings,
        ...unified,
      ],
    }
  },
}
