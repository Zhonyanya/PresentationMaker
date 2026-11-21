import type { TextSlide } from '@/domain/presentation'
import { contentBox, contentChrome, fittedText, lines } from './chrome'
import type { Box, SceneChart, SceneElement, SlideScene } from './scene'
import { sourceTable } from './source-material'
import type { RenderContext } from './types'

type Composition = NonNullable<TextSlide['composition']>
type Comparison = Extract<Composition, { kind: 'comparison' }>
const comparisonNumber = new Intl.NumberFormat('ru', { maximumSignificantDigits: 17 })

export function formatComparisonValue(value: number, unit = ''): string {
  const formatted = value > 0 && value < 0.000001
    ? value.toExponential().replace('.', ',')
    : comparisonNumber.format(value)
  return formatted + unit
}

export function compositionAsText(composition: Composition): string[] {
  if (composition.kind === 'metric') {
    return composition.values.map(({ label, value }) => `${label} — ${value}`)
  }
  if (composition.kind === 'caveats') {
    return composition.items.map(({ title, detail }) => `${title}. ${detail}`)
  }
  return composition.categories.map((category, index) => {
    const values = composition.series.map((series) => (
      `${series.label} — ${formatComparisonValue(series.values[index], composition.unit)}`
    ))
    return `${category}. ${values.join(', ')}`
  })
}

function compositionText(
  ctx: RenderContext, field: string, content: string, box: Box,
  size: { max: number; min: number }, color: string, bold = false, placeholder?: string,
) {
  const { fonts, typography } = ctx.theme
  return fittedText({
    field, box, paragraphs: lines(content), size, placeholder, floor: typography.absoluteMinFontSize,
    style: {
      fontFace: bold ? fonts.heading : fonts.body, color, bold, align: 'left', valign: 'top',
      lineSpacing: 1.04, paragraphSpacing: 8,
    },
  })
}

function comparisonChart(
  composition: Comparison, box: Box, ctx: RenderContext,
): SceneChart | undefined {
  const { colors, fonts, typography } = ctx.theme
  const values = composition.series.flatMap((series) => series.values)
  const valueDecimals = [0, 1, 2, 3, 4, 5, 6, 7, 8].find(
    (precision) => values.every((value) => Number(value.toFixed(precision)) === value),
  )
  if (valueDecimals === undefined) return undefined
  const categoryWidth = box.w * 0.86 / composition.categories.length
  // Use the same conservative spacing for browser labels and native PowerPoint charts.
  const charWidth = typography.chartLabel * 0.68 / 72
  const barWidth = Math.min(categoryWidth * 0.28, 90 / 96)
  if (values.some((value) => formatComparisonValue(value, composition.unit).length * charWidth > barWidth)
      || composition.categories.some((name) => name.length * charWidth > categoryWidth * 1.8)
      || composition.series.reduce((sum, series) => sum + series.label.length * charWidth + 0.35, 0) > box.w) {
    return undefined
  }
  const largest = Math.max(...values) || 1
  const roughInterval = largest / 4
  const exponent = Math.floor(Math.log10(roughInterval))
  const power = 10 ** exponent
  const scaledInterval = roughInterval / power
  const multiplier = [1, 2, 2.5, 5, 10].find((value) => value + 1e-12 >= scaledInterval) ?? 10
  const interval = multiplier * power
  // Keep room above the highest bar for its value label.
  const maximum = interval * (Math.floor(largest / interval + 1e-9) + 1)
  const decimals = Math.max(0, -exponent + Number(multiplier === 2.5))
  const axisLabel = new Intl.NumberFormat('ru', { maximumFractionDigits: decimals }).format(maximum)
  if ((axisLabel.length + (composition.unit?.length ?? 0)) * charWidth + 0.08 > box.w * 0.11) {
    return undefined
  }
  return {
    type: 'chart', box, categories: composition.categories, unit: composition.unit,
    series: composition.series.map((series, index) => ({
      ...series, color: index === 0 ? colors.textMuted : colors.accent,
    })),
    maximum, interval, decimals, valueDecimals, fontFace: fonts.body, textColor: colors.text,
    gridColor: colors.divider, labelSize: typography.chartLabel,
  }
}

function comparisonElements(
  slide: TextSlide, composition: Comparison, ctx: RenderContext,
): SceneElement[] {
  const box = contentBox(ctx)
  const { colors, typography } = ctx.theme
  const hasContext = Boolean(slide.body.trim())
  const chartWidth = hasContext ? box.w * 0.7 : box.w
  const visualBox = { ...box, w: chartWidth }
  const visual = comparisonChart(composition, visualBox, ctx) ?? sourceTable([
    ['Группа', ...composition.series.map((series) => series.label)],
    ...composition.categories.map((name, index) => [
      name, ...composition.series.map(({ values }) => formatComparisonValue(values[index], composition.unit)),
    ]),
  ], visualBox, ctx.theme.fonts.body, typography.absoluteMinFontSize)
  if (!hasContext) return [visual]
  const asideX = box.x + chartWidth + 0.28
  const asideWidth = box.w - chartWidth - 0.28
  const [takeaway, ...details] = lines(slide.body).map((paragraph) => paragraph.text)
  const innerX = asideX + 0.26
  const innerWidth = asideWidth - 0.52
  return [
    visual,
    { type: 'rect', box: { x: asideX, y: box.y + 0.42, w: asideWidth, h: box.h - 0.58 }, fill: colors.surface },
    { type: 'rect', box: { x: asideX, y: box.y + 0.42, w: 0.055, h: box.h - 0.58 }, fill: colors.accent },
    compositionText(ctx, 'body', takeaway, {
      x: innerX, y: box.y + 0.82, w: innerWidth, h: details.length ? 1.25 : box.h - 1.23,
    }, typography.heading, colors.primary, true, 'Вывод'),
    ...(details.length ? [compositionText(ctx, 'body', details.join('\n'), {
      x: innerX, y: box.y + 2.24, w: innerWidth, h: box.h - 2.67,
    }, typography.body, colors.text)] : []),
  ]
}

function contextElements(slide: TextSlide, ctx: RenderContext): SceneElement[] {
  if (!slide.body.trim()) return []
  const box = contentBox(ctx)
  const { colors, typography } = ctx.theme
  const y = box.y + box.h * 0.75
  const h = box.h * 0.25
  return [
    { type: 'rect', box: { x: box.x, y, w: box.w, h }, fill: colors.surface },
    { type: 'rect', box: { x: box.x, y, w: 0.055, h }, fill: colors.accent },
    compositionText(ctx, 'body', slide.body,
      { x: box.x + 0.28, y: y + 0.18, w: box.w - 0.56, h: h - 0.31 },
      typography.body, colors.text, false, 'Контекст'),
  ]
}

function metricElements(
  slide: TextSlide, composition: Extract<Composition, { kind: 'metric' }>, ctx: RenderContext,
): SceneElement[] {
  const box = contentBox(ctx)
  const { colors, typography } = ctx.theme
  const width = box.w / 2
  return [...composition.values.flatMap((item, index): SceneElement[] => {
    const x = box.x + index * width
    const foreground = index === 0 ? colors.primary : colors.textOnPrimary
    return [
      { type: 'rect', box: { x, y: box.y, w: width, h: box.h * 0.65 },
        fill: index === 0 ? colors.surface : colors.primary },
      compositionText(ctx, 'metricLabel', item.label,
        { x: x + 0.36, y: box.y + 0.3, w: width - 0.72, h: 0.48 },
        { max: typography.columnHeading, min: 13 }, foreground, true),
      compositionText(ctx, 'metricValue', item.value,
        { x: x + 0.36, y: box.y + 1.03, w: width - 0.72, h: box.h * 0.65 - 1.24 },
        typography.metricValue, foreground, true),
    ]
  }), ...contextElements(slide, ctx)]
}

function caveatsElements(
  slide: TextSlide, composition: Extract<Composition, { kind: 'caveats' }>, ctx: RenderContext,
): SceneElement[] {
  const box = contentBox(ctx)
  const { colors, spacing, typography } = ctx.theme
  const width = (box.w - spacing.columnGap) / 2
  const available = box.h * (slide.body.trim() ? 0.66 : 0.97)
  return [...composition.items.flatMap((item, index): SceneElement[] => {
    const x = box.x + index * (width + spacing.columnGap)
    return [
      { type: 'rect', box: { x, y: box.y, w: width, h: 0.045 },
        fill: index === 0 ? colors.accent : colors.textMuted },
      compositionText(ctx, 'caveatTitle', item.title,
        { x, y: box.y + 0.25, w: width, h: 0.85 },
        { max: typography.heading.max, min: typography.heading.min }, colors.primary, true),
      compositionText(ctx, 'caveatDetail', item.detail,
        { x, y: box.y + 1.22, w: width, h: available - 1.22 },
        typography.body, colors.text),
    ]
  }), ...contextElements(slide, ctx)]
}

export function buildComposition(slide: TextSlide, composition: Composition, ctx: RenderContext): SlideScene {
  const elements = composition.kind === 'comparison' ? comparisonElements(slide, composition, ctx)
    : composition.kind === 'metric' ? metricElements(slide, composition, ctx)
      : caveatsElements(slide, composition, ctx)
  return {
    background: ctx.theme.colors.background,
    elements: [...contentChrome(slide.title, ctx), ...elements],
  }
}
