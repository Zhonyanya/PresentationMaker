import type PptxGenJS from 'pptxgenjs'
import type { Presentation } from '@/domain/presentation'
import { buildPresentationScenes } from '@/layouts/registry'
import type { SceneElement, SceneText } from '@/layouts/scene'
import { themeFor, type PresentationTheme } from '@/theme/presentation-theme'
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
  const runs = element.paragraphs.map((paragraph, index) => ({
    text: sanitizeText(paragraph.text),
    options: {
      breakLine: index < element.paragraphs.length - 1,
      bullet: paragraph.bullet ? { indent: style.bulletIndent ?? 18 } : false,
      paraSpaceAfter: index < element.paragraphs.length - 1 ? style.paragraphSpacing : 0,
    },
  }))
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
        path: element.src,
        ...element.box,
        sizing: { type: 'contain', w: element.box.w, h: element.box.h },
      })
      break
    case 'text':
      addText(slide, element)
      break
  }
}

export async function buildPptx(presentation: Presentation, options: ExportOptions = {}): Promise<ArrayBuffer> {
  const theme = options.theme ?? themeFor(presentation.brandbook)
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
  const branded = Boolean(presentation.brandbook || options.theme)
  const bytes = await pptx.write({ outputType: 'arraybuffer', compression: !branded }) as ArrayBuffer
  if (!branded) return bytes

  // PptxGenJS позволяет задать шрифты темы, но записывает фиксированную палитру Office.
  const { default: JSZip } = await import('jszip')
  const zip = await JSZip.loadAsync(bytes)
  const themePath = 'ppt/theme/theme1.xml'
  const xml = await zip.file(themePath)!.async('string')
  zip.file(themePath, xml.replace(/(<a:accent([12])><a:srgbClr val=")[0-9a-f]{6}/gi,
    (_, prefix: string, slot: string) => prefix + hex(slot === '1' ? theme.colors.primary : theme.colors.accent)))
  return zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
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
  const bytes = await buildPptx(presentation, options)
  const name = toFileName(fileName.replace(/\.pptx$/i, ''))
  const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  try {
    link.click()
  } finally {
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return name
}
