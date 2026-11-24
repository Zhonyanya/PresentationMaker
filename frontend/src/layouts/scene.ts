/**
 * «Сцена» слайда — платформенно-независимое описание того, что нарисовано
 * на слайде: прямоугольники, тексты и изображения с координатами в дюймах.
 *
 * Сцену строят определения макетов (src/layouts/definitions/*), а
 * потребляют два рендерера:
 *  - SlideRenderer (превью в браузере);
 *  - pptx-export (PptxGenJS).
 * Поэтому превью и PPTX всегда совпадают.
 */

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface SceneParagraph {
  text: string
  bullet?: boolean
  emphasis?: { start: number; end: number }[]
}

export function paragraphRuns({ text, emphasis = [] }: SceneParagraph) {
  const runs: { text: string; emphasized?: boolean }[] = []
  let start = 0
  for (const range of emphasis) {
    if (start < range.start) runs.push({ text: text.slice(start, range.start) })
    runs.push({ text: text.slice(range.start, range.end), emphasized: true })
    start = range.end
  }
  if (start < text.length) runs.push({ text: text.slice(start) })
  return runs
}

export interface TextStyle {
  fontFace: string
  /** pt */
  fontSize: number
  color: string
  emphasisColor?: string
  bold?: boolean
  align: 'left' | 'center' | 'right'
  valign: 'top' | 'middle' | 'bottom'
  lineSpacing: number
  /** pt */
  paragraphSpacing: number
  /** pt, отступ текста от маркера */
  bulletIndent?: number
}

export interface SceneRect {
  type: 'rect'
  box: Box
  fill: string
}

export interface SceneText {
  type: 'text'
  /** Какое поле слайда отображает элемент — для подсветки и предупреждений */
  field: string
  box: Box
  paragraphs: SceneParagraph[]
  style: TextStyle
  /** Подсказка для пустого поля в редакторе. В PPTX пустые поля не выводятся. */
  placeholder?: string
  /** Текст не поместился даже при минимальном размере шрифта */
  overflow: boolean
  /** Шрифт уменьшен относительно размера по умолчанию */
  shrunk: boolean
}

export interface SceneImage {
  type: 'image'
  box: Box
  src: string
}

export interface SceneTable {
  type: 'table'
  box: Box
  rows: string[][]
  merges?: TableMerge[]
  fontSize: number
  fontFace: string
  padding: number
  columnWidths: number[]
  rowHeights: number[]
  comparisonStyle?: {
    headerFill: string
    headerText: string
    rowFill: string
    alternateFill: string
    bodyText: string
  }
}

export interface TableMerge {
  row: number
  column: number
  rowspan: number
  colspan: number
}

export interface SceneChart {
  type: 'chart'
  box: Box
  /** Plot bounds as fractions of the chart box. */
  plot: Box
  categories: string[]
  series: { label: string; values: number[]; color: string }[]
  unit?: '%'
  maximum: number
  interval: number
  decimals: number
  valueDecimals: number
  fontFace: string
  textColor: string
  gridColor: string
  labelSize: number
}

export type SceneElement = SceneRect | SceneText | SceneImage | SceneTable | SceneChart

export interface SlideScene {
  background: string
  backgroundImage?: string
  elements: SceneElement[]
}

export function isEmptyText(element: SceneText): boolean {
  return element.paragraphs.every((p) => p.text.trim() === '')
}
