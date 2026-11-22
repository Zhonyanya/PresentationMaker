import type { TextSlide } from '@/domain/presentation'
import { contentBox, contentChrome, fittedText, lines } from './chrome'
import { firstSentence, paragraphsOf } from './content-utils'
import type { Box, SceneChart, SceneElement, SlideScene } from './scene'
import { comparisonTableStyle, sourceTable } from './source-material'
import { countLines, LINE_HEIGHT_FACTOR } from './text-fit'
import type { RenderContext } from './types'

type Composition = NonNullable<TextSlide['composition']>
type Comparison = Extract<Composition, { kind: 'comparison' }>
const comparisonNumber = new Intl.NumberFormat('ru', { maximumSignificantDigits: 17 })

export function formatComparisonValue(value: number, unit = '', decimals?: number): string {
  if (decimals !== undefined) {
    return new Intl.NumberFormat('ru', {
      minimumFractionDigits: decimals, maximumFractionDigits: decimals,
    }).format(value) + unit
  }
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
  const plotWidth = 0.86
  const categoryWidth = box.w * plotWidth / composition.categories.length
  // Use the same conservative spacing for browser labels and native PowerPoint charts.
  const charWidth = typography.chartLabel * 0.68 / 72
  const barWidth = Math.min(categoryWidth * 0.28, 90 / 96)
  if (values.some((value) => formatComparisonValue(value, composition.unit, valueDecimals).length * charWidth > barWidth)
      || composition.series.reduce((sum, series) => sum + series.label.length * charWidth + 0.35, 0) > box.w) {
    return undefined
  }
  const charsPerLabelLine = Math.floor(categoryWidth * 0.96 / (typography.chartLabel * 0.62 / 72))
  if (composition.categories.some((name) => name.split(/[\s-]+/).some((word) => (
    word.length > charsPerLabelLine
  )))) return undefined
  const labelLines = Math.max(...composition.categories.map((name) => (
    countLines(name.replace(/-/g, '- '), charsPerLabelLine)
  )))
  if (labelLines > 3) return undefined
  const labelLineHeight = LINE_HEIGHT_FACTOR * typography.chartLabel / 72
  // The legend and the highest value label each need a line above the plot.
  const top = Math.max(0.15, (2 * labelLineHeight + 0.19) / box.h)
  const labelHeight = labelLines * labelLineHeight + 0.12
  const bottom = Math.max(0.18, labelHeight / box.h)
  const plotHeight = 1 - top - bottom
  if (plotHeight * box.h < 4 * labelLineHeight) return undefined
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
  const axisLabel = formatComparisonValue(maximum, composition.unit, decimals)
  if (axisLabel.length * charWidth + 0.08 > box.w * 0.11) {
    return undefined
  }
  return {
    type: 'chart', box, categories: composition.categories, unit: composition.unit,
    plot: { x: 0.11, y: top, w: plotWidth, h: plotHeight },
    series: composition.series.map((series, index) => ({
      ...series, color: index === 0 ? colors.textMuted : colors.accent,
    })),
    maximum, interval, decimals, valueDecimals, fontFace: fonts.body, textColor: colors.text,
    gridColor: colors.divider, labelSize: typography.chartLabel,
  }
}

function comparisonTable(composition: Comparison, box: Box, ctx: RenderContext) {
  return sourceTable([
    ['Группа', ...composition.series.map((series) => series.label)],
    ...composition.categories.map((name, index) => [
      name, ...composition.series.map(({ values }) => formatComparisonValue(values[index], composition.unit)),
    ]),
  ], box, ctx.theme.fonts.body, ctx.theme.typography.absoluteMinFontSize, undefined,
  comparisonTableStyle(ctx.theme))
}

function comparisonElements(
  slide: TextSlide, composition: Comparison, ctx: RenderContext,
): SceneElement[] {
  const box = contentBox(ctx)
  const { colors, typography } = ctx.theme
  const wideChart = comparisonChart(composition, box, ctx)
  const [first, ...remaining] = paragraphsOf(slide.body)
  if (!first) return [wideChart ?? comparisonTable(composition, box, ctx)]

  const gap = 0.24
  const padding = 0.23
  const textSize = { ...typography.body, min: Math.min(typography.body.max, Math.max(16, typography.body.min)) }
  const inset = (area: Box): Box => ({
    x: area.x + padding, y: area.y + padding,
    w: area.w - 2 * padding, h: area.h - 2 * padding,
  })
  const panel = (area: Box): SceneElement[] => [
    { type: 'rect', box: area, fill: colors.surface },
    { type: 'rect', box: { ...area, w: 0.055 }, fill: colors.accent },
  ]
  const chartBox = { ...box, w: box.w * 0.7 }
  const sideChart = comparisonChart(composition, chartBox, ctx)
  const side = { ...box, x: box.x + chartBox.w + gap,
    w: box.w - chartBox.w - gap, y: box.y + 0.4, h: Math.min(1.9, box.h - 0.4) }
  const sideText = compositionText(ctx, 'body', slide.body, inset(side),
    textSize, colors.text, false, 'Вывод')
  if (!sideText.overflow && (sideChart || !wideChart)) {
    const visual = sideChart ?? comparisonTable(composition, chartBox, ctx)
    if (visual.box.h <= chartBox.h) return [visual, ...panel(side), sideText]
  }

  const takeaway = firstSentence(first)
  const details = [first.slice(takeaway.length).trim(), ...remaining].filter(Boolean).join('\n')
  const bands = [
    { fraction: 0.29, split: true },
    { fraction: 0.37, split: true },
    { fraction: 0.46, split: true },
    { fraction: 0.46, split: false },
  ]
  for (const { fraction, split } of bands) {
    const height = box.h * fraction
    const area = { ...box, y: box.y + box.h - height, h: height }
    const inner = inset(area)
    const columnWidth = inner.w * 0.38
    const start = split && details ? { ...inner, w: columnWidth } : inner
    const leadText = compositionText(ctx, 'body', split ? takeaway : slide.body, start,
      textSize, split ? colors.primary : colors.text, split, 'Вывод')
    const context = [leadText]
    if (split && details) {
      context.push(compositionText(ctx, 'body', details, {
        ...inner, x: inner.x + columnWidth + gap, w: inner.w - columnWidth - gap,
      }, textSize, colors.text, false, 'Пояснение'))
    }
    if (context.some((text) => text.overflow)) continue
    const visualBox = { ...box, h: box.h - height - gap }
    const visual = wideChart
      ? comparisonChart(composition, visualBox, ctx)
      : comparisonTable(composition, visualBox, ctx)
    if (visual && visual.box.h <= visualBox.h) return [visual, ...panel(area), ...context]
  }

  // A dense explanation can use as much of the row as the comparison itself.
  for (const fraction of [0.58, 0.51, 0.46]) {
    const visualBox = { ...box, w: box.w * fraction }
    const area = { ...box, x: box.x + visualBox.w + gap, w: box.w - visualBox.w - gap }
    const text = compositionText(ctx, 'body', slide.body, inset(area), textSize, colors.text)
    if (text.overflow) continue
    const visual = comparisonChart(composition, visualBox, ctx)
      ?? comparisonTable(composition, visualBox, ctx)
    if (visual.box.h <= visualBox.h
        && (visual.type === 'chart' || visual.fontSize >= Math.min(14, typography.body.min))) {
      return [visual, ...panel(area), text]
    }
  }

  // Keep full text and the usual overflow indication for unusually dense input.
  const area = { ...side, h: box.h - 0.4 }
  const visual = sideChart ?? comparisonTable(composition, chartBox, ctx)
  return [visual, ...panel(area), compositionText(ctx, 'body', slide.body, inset(area),
    typography.body, colors.text, false, 'Вывод')]
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
