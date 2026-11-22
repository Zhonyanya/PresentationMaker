import type { TextSlide } from '@/domain/presentation'
import { contentBox, fittedText, lines } from './chrome'
import { firstSentence, sentencesOf } from './content-utils'
import type { Box, SceneElement, SceneParagraph, SceneText } from './scene'
import type { RenderContext } from './types'
import { estimateTextHeight } from './text-fit'

const monthNames = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август',
  'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
  'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
  'september', 'october', 'november', 'december',
].join('|')
const periodLabel = new RegExp(String.raw`^((?:\d{4}|(?:${monthNames})(?: \d{4})?):)\s+`, 'i')

function readPeriodComparison(body: string) {
  const first = firstSentence(body)
  const afterFirst = body.slice(first.length).trimStart()
  const second = firstSentence(afterFirst)
  const details = afterFirst.slice(second.length).trimStart()
  const firstLabel = first.match(periodLabel)
  const secondLabel = second.match(periodLabel)
  if (!firstLabel || !secondLabel || firstLabel[1].toLowerCase() === secondLabel[1].toLowerCase()
      || details.match(periodLabel)) return undefined
  const periods = [
    { label: firstLabel[1], value: first.slice(firstLabel[0].length) },
    { label: secondLabel[1], value: second.slice(secondLabel[0].length) },
  ]
  if (periods.some(({ value }) => !/\d/.test(value))) return undefined
  return { periods, details: lines(details) }
}

const measuresHeading = /^(?:что изменили|что сделали|изменения|принятые меры|меры пилота|changes made|measures taken)$/i
const dependentClause = /^(?:если|иначе|затем|потом|после этого|при этом|при условии|но|однако|поэтому|и|if|otherwise|then|after that|but|however|therefore|and)(?:\s|,)/i
const delimiters = new Map([['(', ')'], ['[', ']'], ['«', '»'], ['“', '”'], ['"', '"']])
const closingDelimiters = new Set(delimiters.values())

function readMeasures(title: string, paragraphs: SceneParagraph[]) {
  if (paragraphs.length !== 1 || !measuresHeading.test(title.trim().replace(/:$/, ''))) return undefined
  const [{ text }] = paragraphs
  const ends: string[] = []
  const measures: SceneParagraph[] = []
  let start = 0
  for (let index = 0; index < text.length; index++) {
    const char = text[index]
    const closing = delimiters.get(char)
    if (char === ends.at(-1)) ends.pop()
    else if (closing) ends.push(closing)
    else if (closingDelimiters.has(char)) return undefined
    else if (char === ';' && !ends.length) {
      measures.push({ text: text.slice(start, index).trim() })
      start = index + 1
    }
  }
  if (ends.length) return undefined
  measures.push({ text: text.slice(start).trim() })
  if (measures.length < 3 || measures.length > 6
      || measures.some((measure) => measure.text.length < 8 || dependentClause.test(measure.text))) {
    return undefined
  }
  return measures
}

function readTree(body: string) {
  const rows = body.split(/\r?\n/).filter((row) => row.trim())
  const [root, ...outline] = rows
  if (!root || root !== root.trimStart()) return undefined
  const branches: { label: string; children: string[] }[] = []
  for (const row of outline) {
    if (/^(?: {2}|\t)(?=\S)/.test(row)) {
      const branch = branches.at(-1)
      if (!branch || branch.children.length === 2) return undefined
      branch.children.push(row.trim())
    } else {
      if (row !== row.trimStart()) return undefined
      branches.push({ label: row.trim(), children: [] })
    }
  }
  if (branches.length < 2 || branches.length > 3 || branches.some(({ children }) => !children.length)) {
    return undefined
  }
  return { root: root.trim(), branches }
}

function paragraphColumns(paragraphs: SceneParagraph[], ctx: RenderContext): SceneElement[] | undefined {
  if (paragraphs.length < 2) return undefined
  const { colors, fonts, typography } = ctx.theme
  const box = contentBox(ctx)
  const gap = 0.52
  const width = (box.w - gap) / 2
  const style = {
    fontFace: fonts.body, color: colors.text, align: 'left' as const, valign: 'top' as const,
    lineSpacing: typography.lineSpacing, paragraphSpacing: typography.paragraphSpacing,
  }
  const size = { max: typography.body.max, min: Math.min(typography.body.max, Math.max(16, typography.body.min)) }
  const weights = paragraphs.map((paragraph) =>
    estimateTextHeight([paragraph], width, size.max, style) + style.paragraphSpacing / 72)
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  let best = 1
  let bestDistance = Infinity
  let left = 0
  for (let index = 1; index < paragraphs.length; index += 1) {
    left += weights[index - 1]
    const distance = Math.abs(total - 2 * left)
    if (distance < bestDistance) {
      best = index
      bestDistance = distance
    }
  }

  const columns = [paragraphs.slice(0, best), paragraphs.slice(best)].map((items, index) => fittedText({
    field: 'body',
    box: { ...box, x: box.x + index * (width + gap), w: width },
    paragraphs: items,
    size,
    style,
  }))
  if (columns.some(({ overflow }) => overflow)) return undefined
  const fontSize = Math.min(...columns.map((column) => column.style.fontSize))
  for (const column of columns) column.style.fontSize = fontSize
  const height = Math.max(...columns.map((column) => estimateTextHeight(
    column.paragraphs, width, fontSize, style,
  )))
  return [
    { type: 'rect', fill: colors.divider,
      box: { x: box.x + width + gap / 2, y: box.y, w: 0.013, h: height } },
    ...columns,
  ]
}

const statisticLabel = /^\p{L}[\p{L}\p{M}\d ()/–-]{1,42}:(?=\s)/u
const statisticValue = /(?<![\p{L}\p{N}])[+−-]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[,.]\d+)?(?:[–—-]\d+)?(?:[ \u00a0\u202f]*%)?(?![\p{L}\p{N}])/gu
const yearOrRange = /^(?:19|20)\d{2}(?:[–—-]\d{2,4})?$/

function statisticGroups(paragraphs: SceneParagraph[], ctx: RenderContext): SceneElement[] | undefined {
  const sentences = paragraphs.flatMap(({ text }) => sentencesOf(text).map((sentence) => ({ text: sentence })))
  const groups: SceneParagraph[] = []
  for (const { text } of sentences) {
    const label = text.match(statisticLabel)?.[0]
    if (!label) break
    const numericRanges = Array.from(text.slice(label.length).matchAll(statisticValue))
      .filter(([value]) => !yearOrRange.test(value))
      .map(({ 0: value, index }) => ({ start: label.length + index, end: label.length + index + value.length }))
    if (!numericRanges.length) break
    groups.push({ text, emphasis: [{ start: 0, end: label.length }, ...numericRanges] })
  }
  if (groups.length < 2 || groups.length > 3) return undefined

  const details = sentences.slice(groups.length)
  const { colors, fonts, typography } = ctx.theme
  const box = contentBox(ctx)
  const gap = 0.26
  const padding = 0.25
  const width = (box.w - gap * (groups.length - 1)) / groups.length
  const style = {
    fontFace: fonts.body, color: colors.text, emphasisColor: colors.primary,
    align: 'left' as const, valign: 'top' as const,
    lineSpacing: 1.08, paragraphSpacing: typography.paragraphSpacing,
  }
  const size = { max: typography.body.max, min: Math.min(typography.body.max, 16) }
  const groupSize = { ...size, max: Math.max(size.max, Math.min(24, typography.heading.min)) }
  const contentWidth = width - 2 * padding
  const naturalHeight = Math.max(...groups.map((group) => (
    estimateTextHeight([group], contentWidth, groupSize.max, style) / 0.96
  )))
  const height = Math.min(box.h * (details.length ? 0.68 : 1), Math.max(1.9, naturalHeight + 2 * padding))
  const y = box.y + (details.length ? 0 : Math.min(0.45, (box.h - height) / 2))
  const cards = groups.map((group, index) => {
    const area = { x: box.x + index * (width + gap), y, w: width, h: height }
    const content = fittedText({
      field: 'body', paragraphs: [group], size: groupSize, style,
      box: { x: area.x + padding, y: area.y + padding, w: contentWidth, h: height - 2 * padding },
    })
    return { area, content }
  })
  if (cards.some(({ content }) => content.overflow)) return undefined
  const fontSize = Math.min(...cards.map(({ content }) => content.style.fontSize))
  const elements = cards.flatMap(({ area, content }): SceneElement[] => [
    { type: 'rect', box: area, fill: colors.surface },
    { type: 'rect', box: { ...area, h: 0.055 }, fill: colors.accent },
    { ...content, style: { ...content.style, fontSize } },
  ])
  if (!details.length) return elements
  const context = fittedText({
    field: 'body', paragraphs: details, size, style,
    box: { x: box.x, y: box.y + height + gap, w: box.w, h: box.h - height - gap },
  })
  return context.overflow ? undefined : [...elements, context]
}

export function textComposition(slide: TextSlide, ctx: RenderContext): SceneElement[] | undefined {
  const paragraphs = lines(slide.body)
  if (!paragraphs.length) return undefined
  const { colors, typography, fonts } = ctx.theme
  const box = contentBox(ctx)
  const padding = 0.26
  const gap = 0.18
  const texts: SceneText[] = []
  const backgrounds: SceneElement[] = []
  const text = (content: SceneParagraph[], bounds: Box, options: {
    accent?: boolean; heading?: boolean; max?: number
    field?: 'body' | 'stepNumber'; valign?: 'top' | 'middle'
  } = {}) => {
    const { accent = false, heading = false, max = typography.body.max, field = 'body',
      valign = 'middle' } = options
    const element = fittedText({
      field, box: bounds, paragraphs: content, size: { max, min: 16 },
      style: {
        fontFace: accent || heading ? fonts.heading : fonts.body,
        color: accent ? colors.textOnPrimary : heading ? colors.primary : colors.text,
        bold: accent || heading, align: field === 'stepNumber' ? 'center' : 'left',
        valign, lineSpacing: 1.04, paragraphSpacing: typography.paragraphSpacing,
        bulletIndent: typography.bulletIndent,
      },
    })
    texts.push(element)
    return element
  }
  const surface = (bounds: Box, fill = colors.surface) =>
    backgrounds.push({ type: 'rect', box: bounds, fill })
  const inset = (bounds: Box): Box => ({
    x: bounds.x + padding, y: bounds.y + padding,
    w: bounds.w - 2 * padding, h: bounds.h - 2 * padding,
  })
  const drawBlocks = (items: SceneParagraph[], columns: number) => {
    const rows = Math.ceil(items.length / columns)
    const width = (box.w - (columns - 1) * gap) / columns
    const height = Math.min(box.h * 0.72, (box.h - (rows - 1) * gap) / rows)
    items.forEach((item, index) => {
      const row = Math.floor(index / columns)
      const filled = Math.min(columns, items.length - row * columns)
      const column = index % columns + (columns - filled) / 2
      const card = { ...box, x: box.x + column * (width + gap), y: box.y + row * (height + gap),
        w: width, h: height }
      surface(card)
      surface({ ...card, h: 0.06 }, colors.accent)
      text([item], inset(card))
    })
  }
  switch (slide.textStyle) {
    case 'tree': {
      const tree = readTree(slide.body)
      if (!tree) return undefined
      const rootIsTitle = tree.root === slide.title.trim()
      const columnGap = 0.26
      const columnWidth = (box.w - (tree.branches.length - 1) * columnGap) / tree.branches.length
      const columnTop = rootIsTitle ? box.y : box.y + 0.77
      const columnHeight = Math.min(3.25, box.y + box.h - columnTop)
      if (!rootIsTitle) {
        text([{ text: tree.root }], { ...box, h: 0.6 }, { heading: true, max: 21, valign: 'top' })
      }
      tree.branches.forEach(({ label, children }, index) => {
        const column = { x: box.x + index * (columnWidth + columnGap), y: columnTop,
          w: columnWidth, h: columnHeight }
        const inner = inset(column)
        const headingHeight = 0.74
        surface(column)
        text([{ text: label }], { ...inner, h: headingHeight },
          { heading: true, max: 20, valign: 'top' })
        text(children.map((child) => ({ text: child, bullet: true })), {
          ...inner, y: inner.y + headingHeight + gap, h: inner.h - headingHeight - gap,
        }, { valign: 'top' })
      })
      break
    }
    case 'blocks': {
      if (paragraphs.length < 2 || paragraphs.length > 3) return undefined
      drawBlocks(paragraphs, paragraphs.length)
      break
    }
    case 'steps': {
      const sections = slide.body.trim().split(/\r?\n[ \t]*\r?\n/)
      const [label, ...conditions] = sections.length === 2 ? lines(sections[1]) : []
      const hasConditions = conditions.length > 0
        && /^(?:Условия|Условие|Conditions?|Requirements?)(?:\s|$)/i.test(label.text)
      const steps = hasConditions ? lines(sections[0]) : paragraphs
      if (steps.length < 2 || steps.length > 4
          || steps.some(({ text }) => /^\d+[.)]\s/.test(text))) return undefined
      const stepsWidth = hasConditions ? box.w * 0.66 : box.w
      const height = (box.h - (steps.length - 1) * gap) / steps.length
      steps.forEach((paragraph, index) => {
        const row = { ...box, y: box.y + index * (height + gap), w: stepsWidth, h: height }
        const numberBox = { ...row, w: 0.64 }
        surface(row)
        surface(numberBox, colors.primary)
        text([{ text: String(index + 1) }], numberBox, { accent: true, field: 'stepNumber' })
        text([paragraph], inset({ ...row, x: row.x + 0.64, w: row.w - 0.64 }))
      })
      if (hasConditions) {
        const conditionsBox = { ...box, x: box.x + stepsWidth + gap, w: box.w - stepsWidth - gap }
        const inner = inset(conditionsBox)
        const headingHeight = 0.76
        surface(conditionsBox)
        surface({ ...conditionsBox, h: 0.06 }, colors.accent)
        text([label], { ...inner, h: headingHeight }, { heading: true, max: 20, valign: 'top' })
        text(conditions, { ...inner, y: inner.y + headingHeight + gap,
          h: inner.h - headingHeight - gap }, { valign: 'top' })
      }
      break
    }
    case 'lead':
    default: {
      const measures = slide.textStyle ? undefined : readMeasures(slide.title, paragraphs)
      if (measures) {
        drawBlocks(measures.map(({ text }) => ({
          text: text.replace(/^\p{Ll}/u, (letter) => letter.toUpperCase()),
        })), measures.length === 4 ? 2 : 3)
        break
      }
      const comparison = slide.textStyle ? undefined : readPeriodComparison(slide.body.trim())
      if (comparison) {
        const width = (box.w - gap) / 2
        const height = box.h * (comparison.details.length ? 0.54 : 0.72)
        const values = comparison.periods.map(({ label, value }, index) => {
          const card = { ...box, x: box.x + index * (width + gap), w: width, h: height }
          const inner = inset(card)
          const heading = 0.65
          surface(card)
          surface({ ...card, h: 0.06 }, colors.accent)
          text([{ text: label }], { ...inner, h: heading }, { heading: true, max: 21, valign: 'top' })
          return text([{ text: value }], {
            ...inner, y: inner.y + heading + gap, h: inner.h - heading - gap,
          }, { max: 24, valign: 'top' })
        })
        const fontSize = Math.min(...values.map((value) => value.style.fontSize))
        for (const value of values) value.style.fontSize = fontSize
        if (comparison.details.length) {
          text(comparison.details, {
            x: box.x + padding, y: box.y + height + gap + padding,
            w: box.w - 2 * padding, h: box.h - height - gap - 2 * padding,
          }, { valign: 'top' })
        }
        break
      }
      const statistics = slide.textStyle ? undefined : statisticGroups(paragraphs, ctx)
      if (statistics) return statistics
      const [first, ...rest] = paragraphs
      const lead = slide.textStyle === 'lead' ? first.text : firstSentence(first.text)
      const remainingFirst = first.text.slice(lead.length).trim()
      const details = remainingFirst ? [{ text: remainingFirst }, ...rest] : rest
      if (lead.length > 185 || details.length > 4) return paragraphColumns(paragraphs, ctx)
      if (ctx.sideLead && lead.length <= 110 && details.length
          && details.reduce((sum, item) => sum + item.text.length, 0) <= 320) {
        const highlight = { ...box, w: box.w * 0.40, h: box.h * 0.87 }
        surface(highlight, colors.primary)
        text([{ text: lead }], inset(highlight), { accent: true, max: 26 })
        text(details, inset({ ...box, x: box.x + highlight.w + gap, w: box.w - highlight.w - gap }))
        break
      }
      const highlight = { ...box, h: details.length ? box.h * 0.4 : box.h * 0.58 }
      surface(highlight, colors.primary)
      text([{ text: lead }], inset(highlight), { accent: true, max: Math.max(26, typography.heading.max) })
      if (details.length) {
        text(details, {
          x: box.x + padding, y: box.y + highlight.h + gap,
          w: box.w - 2 * padding, h: box.h - highlight.h - gap,
        })
      }
    }
  }
  if (!texts.some((element) => element.overflow)) return [...backgrounds, ...texts]
  const canFlow = slide.textStyle === 'lead' || slide.textStyle === undefined
  return canFlow ? paragraphColumns(paragraphs, ctx) : undefined
}
