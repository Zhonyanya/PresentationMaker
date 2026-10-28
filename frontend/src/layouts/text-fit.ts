import type { Box, SceneParagraph } from './scene'

/**
 * Оценка размера шрифта, при котором текст помещается в область.
 *
 * Измерять текст «по-настоящему» нельзя: PowerPoint отрисует его сам.
 * Поэтому используется консервативная оценка средней ширины символа
 * с небольшим запасом. Замер в браузере для русского текста в Arial:
 * ~0.52 em для обычного начертания и ~0.56 em для полужирного; берём 0.53 и 0.58.
 * При смене шрифта в теме коэффициенты стоит перепроверить. Одна и та же функция используется и в превью, и в PPTX —
 * так размеры шрифтов везде совпадают.
 */

const POINTS_PER_INCH = 72
/** PowerPoint: одинарный интервал ≈ 1.2 высоты шрифта */
export const LINE_HEIGHT_FACTOR = 1.2

export interface FitOptions {
  max: number
  min: number
  bold?: boolean
  lineSpacing: number
  paragraphSpacing: number
  bulletIndent?: number
  /** Шаг уменьшения, pt */
  step?: number
}

export interface FitResult {
  fontSize: number
  overflow: boolean
  shrunk: boolean
}

function charWidthEm(bold: boolean | undefined): number {
  return bold ? 0.58 : 0.53
}

/** Количество строк, которое займёт абзац при переносе по словам. */
export function countLines(text: string, charsPerLine: number): number {
  if (charsPerLine < 1) return Number.POSITIVE_INFINITY
  const hardLines = text.split('\n')
  let total = 0
  for (const hardLine of hardLines) {
    const words = hardLine.split(/\s+/).filter(Boolean)
    if (words.length === 0) {
      total += 1
      continue
    }
    let lines = 1
    let current = 0
    for (const word of words) {
      const length = word.length
      // Слово длиннее строки переносится по символам
      if (length > charsPerLine) {
        if (current > 0) lines += 1
        const chunks = Math.ceil(length / charsPerLine)
        lines += chunks - 1
        current = length - (chunks - 1) * charsPerLine
        continue
      }
      const needed = current === 0 ? length : current + 1 + length
      if (needed > charsPerLine) {
        lines += 1
        current = length
      } else {
        current = needed
      }
    }
    total += lines
  }
  return total
}

export function estimateTextHeight(
  paragraphs: SceneParagraph[],
  width: number,
  fontSize: number,
  options: Pick<FitOptions, 'bold' | 'lineSpacing' | 'paragraphSpacing' | 'bulletIndent'>,
): number {
  const charWidth = (fontSize / POINTS_PER_INCH) * charWidthEm(options.bold)
  const lineHeight = (fontSize / POINTS_PER_INCH) * LINE_HEIGHT_FACTOR * options.lineSpacing
  const spacing = options.paragraphSpacing / POINTS_PER_INCH
  let height = 0
  paragraphs.forEach((paragraph, index) => {
    const indent = paragraph.bullet ? (options.bulletIndent ?? 0) / POINTS_PER_INCH : 0
    const charsPerLine = Math.floor((width - indent) / charWidth)
    height += countLines(paragraph.text, charsPerLine) * lineHeight
    if (index < paragraphs.length - 1) height += spacing
  })
  return height
}

export function fitText(paragraphs: SceneParagraph[], box: Box, options: FitOptions): FitResult {
  const step = options.step ?? 1
  // Небольшой запас по высоте, чтобы PowerPoint гарантированно не вылез за рамку
  const available = box.h * 0.96
  for (let size = options.max; size >= options.min; size -= step) {
    if (estimateTextHeight(paragraphs, box.w, size, options) <= available) {
      return { fontSize: size, overflow: false, shrunk: size < options.max }
    }
  }
  return { fontSize: options.min, overflow: true, shrunk: true }
}
