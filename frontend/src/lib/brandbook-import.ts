import { sanitizeText } from './text'
import type JSZip from 'jszip'
import { brandbookSchema, fontFamilySchema, type Brandbook } from '@/domain/brandbook'
import { FileImportError, inflatedSize, type StreamableEntry } from './file-import'

export const BRANDBOOK_ACCEPT = '.pptx,.potx,.pdf'
const MAX_THEME_XML = 1024 * 1024
const invalidTemplate = () => new FileImportError('Не удалось прочитать тему PowerPoint. Сохраните шаблон как PPTX или POTX и повторите загрузку.')

async function xmlPart(zip: JSZip, path: string): Promise<Document> {
  const entry = zip.file(path)
  if (!entry || await inflatedSize(entry as unknown as StreamableEntry, MAX_THEME_XML) > MAX_THEME_XML) throw invalidTemplate()
  const xml = new DOMParser().parseFromString(await entry.async('string'), 'application/xml')
  if (xml.getElementsByTagName('parsererror').length) throw invalidTemplate()
  return xml
}

function first(parent: Document | Element | undefined, name: string) {
  return parent?.getElementsByTagNameNS('*', name)[0]
}

async function relatedPart(zip: JSZip, from: string, kind: string, id?: string) {
  const split = from.lastIndexOf('/') + 1
  const relationships = await xmlPart(zip, from.slice(0, split) + '_rels/' + from.slice(split) + '.rels')
  const rel = Array.from(relationships.getElementsByTagNameNS('*', 'Relationship')).find((r) =>
    r.getAttribute('Type')?.endsWith('/' + kind) && (!id || r.getAttribute('Id') === id) && r.getAttribute('TargetMode') !== 'External')
  const target = rel?.getAttribute('Target')
  if (!target) throw invalidTemplate()
  return new URL(target, 'https://package.invalid/' + from).pathname.slice(1)
}

async function powerPointPalette(file: File) {
  const { default: Zip } = await import('jszip')
  const zip = await Zip.loadAsync(await file.arrayBuffer())
  const presentation = 'ppt/presentation.xml'
  const master = first(await xmlPart(zip, presentation), 'sldMasterId')
  const id = Array.from(master?.attributes ?? []).find((attr) => attr.localName === 'id' && attr.namespaceURI)?.value
  const masterPath = await relatedPart(zip, presentation, 'slideMaster', id)
  const theme = await xmlPart(zip, await relatedPart(zip, masterPath, 'theme'))
  const palette = first(theme, 'clrScheme')
  const readColor = (name: string) => {
    const color = first(palette, name)?.firstElementChild
    const hex = color?.getAttribute('lastClr') ?? color?.getAttribute('val')
    return hex && /^[a-fA-F0-9]{6}$/.test(hex) ? '#' + hex.toUpperCase() : undefined
  }
  const primary = readColor('accent1')
  if (!primary) throw invalidTemplate()
  const fonts = first(theme, 'fontScheme')
  const readFont = (name: string) => {
    const family = first(first(fonts, name), 'latin')?.getAttribute('typeface')?.trim()
    const result = fontFamilySchema.safeParse(family)
    return result.success ? result.data : undefined
  }
  return { primary, accent: readColor('accent2') ?? primary, headingFont: readFont('majorFont'), bodyFont: readFont('minorFont') }
}

async function pdfPalette(file: File) {
  const { withPdf, pdfText } = await import('./pdf-import')
  return withPdf(file, async (pdf) => {
    const { text } = await pdfText(pdf, 200_000)
    const codes = [...text.matchAll(/(?:#\s*|\bHEX\s*[:=]?\s*)([0-9a-f]{6})\b/gi)]
    let colors = [...new Set(codes.map((m) => '#' + m[1].toUpperCase()))]
    if (!colors.length) {
      // У графических руководств берём самые частые цвета с первых трёх страниц.
      const counts = new Map<string, number>()
      let darkPixels = 0
      for (let i = 1; i <= Math.min(pdf.numPages, 3); i++) {
        const page = await pdf.getPage(i)
        const size = page.getViewport({ scale: 1 })
        const viewport = page.getViewport({ scale: 160 / Math.max(size.width, size.height) })
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.ceil(viewport.width))
        canvas.height = Math.max(1, Math.ceil(viewport.height))
        try {
          await page.render({ canvas, viewport }).promise
          const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data
          for (let p = 0; p < pixels.length; p += 4) {
            const r = pixels[p], g = pixels[p + 1], b = pixels[p + 2]
            if (Math.min(r, g, b) > 242) continue
            if (Math.max(r, g, b) < 16) { darkPixels++; continue }
            const color = '#' + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1).toUpperCase()
            counts.set(color, (counts.get(color) ?? 0) + 1)
          }
        } finally {
          page.cleanup()
        }
      }
      colors = [...counts].filter(([, count]) => count >= 12).sort((a, b) => b[1] - a[1]).map(([color]) => color)
      if (!colors.length && darkPixels >= 12) colors = ['#000000', '#FFFFFF']
    }
    if (!colors.length) throw new FileImportError('В PDF не найдена палитра. Загрузите брендбук с HEX-кодами цветов или шаблон PowerPoint.')
    return { primary: colors[0], accent: colors[1] ?? colors[0] }
  })
}

export async function readBrandbook(file: File): Promise<Brandbook> {
  if (file.size > 10 * 1024 * 1024) throw new FileImportError('Файл брендбука больше 10 МБ.')
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!ext || !['pptx', 'potx', 'pdf'].includes(ext)) throw new FileImportError('Выберите брендбук в формате PPTX, POTX или PDF.')
  try {
    const palette = ext === 'pdf' ? await pdfPalette(file) : await powerPointPalette(file)
    const name = sanitizeText(file.name.replace(/\.[^.]+$/, '').slice(0, 120)).trim() || 'Брендбук'
    return brandbookSchema.parse({ ...palette, name })
  } catch (error) {
    if (error instanceof FileImportError) throw error
    throw invalidTemplate()
  }
}
