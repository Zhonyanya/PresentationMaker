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
}

export interface TextStyle {
  fontFace: string
  /** pt */
  fontSize: number
  color: string
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

export type SceneElement = SceneRect | SceneText | SceneImage

export interface SlideScene {
  background: string
  elements: SceneElement[]
}

export function isEmptyText(element: SceneText): boolean {
  return element.paragraphs.every((p) => p.text.trim() === '')
}
