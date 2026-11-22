import type PptxGenJS from 'pptxgenjs'
import type { Presentation } from '@/domain/presentation'
import { buildPresentationScenes } from '@/layouts/registry'
import type { SceneElement, SceneText } from '@/layouts/scene'
import { paragraphRuns } from '@/layouts/scene'
import { tableCellStyle, visibleTableCells } from '@/layouts/source-material'
import { presentationTheme, type PresentationTheme } from '@/theme/presentation-theme'
import { sanitizeText } from '@/lib/text'

/**
 * Экспорт в PPTX через PptxGenJS.
 *
 * Каждый элемент «сцены» становится настоящим объектом PowerPoint:
 * прямоугольник — фигурой, текст — текстовым полем (редактируется),
 * логотип — изображением. Скриншоты не используются.
 *
 * Ограничение: PptxGenJS создаёт слайды кодом и не может взять мастер-слайды
 * из готового .potx/.pptx-шаблона. Подробнее — README, «Ограничения».
 */

export interface ExportOptions {
  theme?: PresentationTheme
  includeNotes?: boolean
}

const hex = (color: string) => color.replace('#', '').toUpperCase()

type PptxSlide = ReturnType<PptxGenJS['addSlide']>

function addText(slide: PptxSlide, element: SceneText) {
  if (element.paragraphs.length === 0) return
  const { style, box } = element
  const runs = element.paragraphs.flatMap((paragraph, index) => paragraphRuns(paragraph).map((run, runIndex, parts) => ({
    text: sanitizeText(run.text),
    options: {
      breakLine: runIndex === parts.length - 1 && index < element.paragraphs.length - 1,
      bullet: paragraph.bullet && runIndex === 0 ? { indent: style.bulletIndent ?? 18 } : false,
      paraSpaceAfter: index < element.paragraphs.length - 1 ? style.paragraphSpacing : 0,
      ...(run.emphasized && { bold: true, color: hex(style.emphasisColor ?? style.color) }),
    },
  })))
  slide.addText(runs, {
    x: box.x,
    y: box.y,
    w: box.w,
    h: box.h,
    margin: 0,
    fontFace: style.fontFace,
    fontSize: style.fontSize,
    color: hex(style.color),
    bold: Boolean(style.bold),
    align: style.align,
    valign: style.valign,
    lineSpacingMultiple: style.lineSpacing,
    // Если пользователь допишет текст в PowerPoint — шрифт уменьшится, а не вылезет за рамку
    fit: 'shrink',
    isTextBox: true,
  })
}

function addElement(pptx: PptxGenJS, slide: PptxSlide, element: SceneElement) {
  switch (element.type) {
    case 'rect':
      slide.addShape(pptx.ShapeType.rect, {
        ...element.box,
        fill: { color: hex(element.fill) },
        line: { color: hex(element.fill), width: 0 },
      })
      break
    case 'image':
      slide.addImage({
        ...element.box,
        ...(element.src.startsWith('data:image/png;base64,')
          ? { data: element.src }
          : { path: element.src, sizing: { type: 'contain', w: element.box.w, h: element.box.h } }),
      })
      break
    case 'table': {
      const { x, y, w, h } = element.box
      const rows = visibleTableCells(element.rows, element.merges).map((row, index) => row.map((cell) => {
        const style = tableCellStyle(element, index, cell.column)
        return {
          text: sanitizeText(cell.text),
          options: {
            rowspan: cell.rowspan,
            colspan: cell.colspan,
            ...(style && {
              fill: { color: hex(style.fill) }, color: hex(style.color), bold: style.bold, align: style.align,
            }),
          },
        }
      }))
      slide.addTable(rows, {
        x, y, w, h,
        colW: element.columnWidths,
        autoPage: false,
        fontSize: element.fontSize,
        fontFace: element.fontFace,
        margin: element.padding,
        rowH: element.rowHeights,
        border: { type: 'solid', color: 'CBD5E1', pt: 1 },
        valign: 'middle',
      })
      break
    }
    case 'chart': {
      const numberFormat = (decimals: number) => '0' + (decimals ? `.${'0'.repeat(decimals)}` : '')
        + (element.unit ? `"${element.unit}"` : '')
      slide.addChart(pptx.ChartType.bar, element.series.map((series) => ({
        name: sanitizeText(series.label),
        labels: element.categories.map(sanitizeText),
        values: series.values,
      })), {
        ...element.box,
        layout: element.plot,
        barDir: 'col',
        barGrouping: 'clustered',
        chartColors: element.series.map((series) => hex(series.color)),
        showLegend: true,
        legendPos: 't',
        legendFontFace: element.fontFace,
        legendFontSize: element.labelSize,
        legendColor: hex(element.textColor),
        showValue: true,
        dataLabelFormatCode: numberFormat(element.valueDecimals),
        dataLabelColor: hex(element.textColor),
        dataLabelFontFace: element.fontFace,
        dataLabelFontSize: element.labelSize,
        catAxisLabelFontFace: element.fontFace,
        catAxisLabelFontSize: element.labelSize,
        catAxisLabelColor: hex(element.textColor),
        catAxisLineShow: false,
        catAxisMajorTickMark: 'none',
        valAxisLabelFontFace: element.fontFace,
        valAxisLabelFontSize: element.labelSize,
        valAxisLabelColor: hex(element.textColor),
        valAxisLabelFormatCode: numberFormat(element.decimals),
        valAxisLineShow: false,
        valAxisMajorTickMark: 'none',
        valAxisMinVal: 0,
        valGridLine: { color: hex(element.gridColor), size: 0.5 },
      })
      break
    }
    case 'text':
      addText(slide, element)
      break
  }
}

export async function buildPptx(presentation: Presentation, options: ExportOptions = {}): Promise<PptxGenJS> {
  const theme = options.theme ?? presentationTheme
  const includeNotes = options.includeNotes ?? true
  const { default: PptxGenJSClass } = await import('pptxgenjs')
  const pptx = new PptxGenJSClass()

  pptx.defineLayout({ name: 'THEME', width: theme.slide.width, height: theme.slide.height })
  pptx.layout = 'THEME'
  pptx.title = sanitizeText(presentation.title)
  pptx.subject = pptx.title
  pptx.author = 'Презентатор'
  pptx.theme = { headFontFace: theme.fonts.heading, bodyFontFace: theme.fonts.body }

  const scenes = buildPresentationScenes(presentation.slides, theme)
  presentation.slides.forEach((slideData, index) => {
    const scene = scenes[index]
    const slide = pptx.addSlide()
    slide.background = { color: hex(scene.background) }
    scene.elements.forEach((element) => addElement(pptx, slide, element))
    if (includeNotes && slideData.notes?.trim()) slide.addNotes(sanitizeText(slideData.notes.trim()))
  })
  return pptx
}

/** Безопасное имя файла из названия презентации */
export function toFileName(title: string): string {
  const base = title
    // Невидимые символы форматирования (RLO, zero-width) позволяют подделать вид имени и расширения
    .replace(/\p{Cf}/gu, '')
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120)
    .replace(/[. ]+$/, '')
  return `${base || 'Презентация'}.pptx`
}

/** Собирает PPTX и запускает скачивание в браузере. Возвращает имя файла. */
export async function downloadPptx(presentation: Presentation, fileName: string, options: ExportOptions = {}): Promise<string> {
  const pptx = await buildPptx(presentation, options)
  const name = toFileName(fileName.replace(/\.pptx$/i, ''))
  await pptx.writeFile({ fileName: name, compression: true })
  return name
}
