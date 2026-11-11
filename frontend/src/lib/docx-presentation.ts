import { imageSize } from 'image-size'
import { presentationSchema, type Presentation, type TextSlide } from '@/domain/presentation'
import { sourceTable } from '@/layouts/source-material'
import { presentationTheme } from '@/theme/presentation-theme'
import { FileImportError, readDocxHtml } from './file-import'
import { sanitizeText } from './text'

const MAX_SLIDES = 60
const MAX_IMAGE_URL = 1_500_000
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg'])
const CAPTION = /^(?:рисунок|рис\.|диаграмма|схема|график|figure|fig\.|chart)\s*(?:№\s*)?\d+/iu
const MAX_BODY = 550

function compact(value: string | null): string {
  return sanitizeText(value ?? '').replace(/\s+/g, ' ').trim()
}

async function pngImage(contentType: string, encoded: string): Promise<string> {
  const src = `data:${contentType};base64,${encoded}`
  const bytes = Uint8Array.from(atob(encoded), (char) => char.charCodeAt(0))
  const { type, width, height } = imageSize(bytes)
  if (type !== (contentType === 'image/png' ? 'png' : 'jpg')
    || !width || !height || width * height > 16_000_000) return ''
  if (contentType === 'image/png' && src.length <= MAX_IMAGE_URL) return src
  const bitmap = await createImageBitmap(new Blob([bytes], { type: contentType }))
  try {
    const scale = Math.min(1, 1280 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const png = canvas.toDataURL('image/png')
    return png.length <= MAX_IMAGE_URL ? png : ''
  } finally {
    bitmap.close()
  }
}

function splitTable(table: HTMLTableElement): string[][][] {
  const rows = Array.from(table.rows, (row) => Array.from(row.cells, (cell) => compact(cell.textContent)))
  const columns = rows[0]?.length ?? 0
  if (rows.length < 2 || columns < 2 || columns > 8
    || rows.some((row) => row.length !== columns || row.some((cell) => cell.length > 300))
    || table.querySelector('[rowspan], [colspan], table')) return []

  const { slide, spacing, fonts, typography } = presentationTheme
  const box = { x: 0, y: 0, w: slide.width - 2 * spacing.marginX, h: spacing.contentBottom - spacing.contentTop }
  const fits = (part: string[][]) => part.length <= 10
    && sourceTable(part, box, fonts.body, typography.absoluteMinFontSize).box.h <= box.h
  const parts: string[][][] = []
  const header = table.rows[0].querySelector('th') ? rows[0] : undefined
  let part: string[][] = []
  for (const row of rows) {
    if (!fits([...part, row])) {
      if (part.length < 2) return []
      parts.push(part)
      part = header ? [header] : []
      if (!fits([...part, row])) return []
    }
    part.push(row)
  }
  if (part.length === 1) {
    const previous = parts.at(-1)
    if (!previous || previous.length <= 2) return []
    const last = previous.at(-1)!
    if (!fits([last, ...part])) return []
    previous.pop()
    part.unshift(last)
  }
  parts.push(part)
  return parts
}

export async function importDocxPresentation(file: File): Promise<{ presentation: Presentation; warnings: string[] }> {
  let omittedImages = 0
  let flattenedTables = 0
  let mediaBytes = 0
  const html = await readDocxHtml(file, async (image) => {
    if (IMAGE_TYPES.has(image.contentType)) {
      try {
        const encoded = await image.readAsBase64String()
        if (encoded.length <= 8_000_000 && mediaBytes < 16_000_000) {
          const src = await pngImage(image.contentType, encoded)
          if (src && mediaBytes + src.length <= 16_000_000) {
            mediaBytes += src.length
            return { src }
          }
        }
      } catch {
        // A damaged image should not discard the rest of the document.
      }
    }
    omittedImages += 1
    return { src: '' }
  })
  const document = new DOMParser().parseFromString(html, 'text/html')
  const title = sanitizeText(compact(file.name.replace(/\.docx$/i, '')).slice(0, 200)) || 'Доклад'
  const slides: Presentation['slides'] = [{ id: crypto.randomUUID(), layout: 'title', title }]
  const add = (slide: Omit<TextSlide, 'id' | 'layout'>) => {
    if (slides.length >= MAX_SLIDES) throw new FileImportError('Доклад требует больше 60 слайдов. Разделите DOCX на части.')
    slides.push({ id: crypto.randomUUID(), layout: 'text', ...slide })
  }
  let heading = 'Материалы доклада'
  let body = ''
  const flush = () => {
    if (body) add({ title: heading, body })
    body = ''
  }
  const addText = (text: string) => {
    let remaining = text
    while (remaining) {
      const boundary = remaining.length > MAX_BODY
        ? Math.max(remaining.lastIndexOf(' ', MAX_BODY), 1)
        : remaining.length
      const size = boundary === 1 && remaining.length > MAX_BODY ? MAX_BODY : boundary
      const paragraph = sanitizeText(remaining.slice(0, size).trim())
      remaining = remaining.slice(size).trimStart()
      if (body.length + paragraph.length + 1 > MAX_BODY) flush()
      body = body ? `${body}\n${paragraph}` : paragraph
    }
  }
  const blocks = [...document.body.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,table')]
    .filter((node) => node.tagName === 'TABLE' ? !node.parentElement?.closest('table') : !node.closest('table'))
  for (let index = 0; index < blocks.length; index += 1) {
    const node = blocks[index]
    if (node.tagName === 'TABLE') {
      flush()
      const table = node as HTMLTableElement
      const parts = splitTable(table)
      if (parts.length) {
        parts.forEach((rows, part) => add({
          title: parts.length > 1 ? `Таблица · ${part + 1}/${parts.length}` : 'Таблица',
          body: '', sourceMaterial: { kind: 'table', rows },
        }))
      } else {
        flattenedTables += 1
        for (const row of Array.from(table.rows)) {
          addText(Array.from(row.cells, (cell) => compact(cell.textContent)).filter(Boolean).join(' · '))
        }
        flush()
      }
      continue
    }
    const following = blocks[index + 1]
    const inline = compact(node.textContent)
    const captionBeforeImage = node.tagName === 'P' && CAPTION.test(inline)
      && !node.querySelector('img') && following?.tagName === 'P'
      && Boolean(following.querySelector('img[src^="data:image/png;base64,"]'))
    const imageBlock = captionBeforeImage ? following : node
    const images = [...imageBlock.querySelectorAll('img')].filter((img) => img.closest('p,li') === imageBlock)
    if (images.length) {
      const next = blocks[index + 1]
      const nextText = next?.tagName === 'P' && !next.querySelector('img') ? compact(next.textContent) : ''
      const caption = inline || (CAPTION.test(nextText) ? nextText : '')
      flush()
      for (const image of images) {
        const png = image.getAttribute('src')
        if (png) add({
          title: 'Иллюстрация', body: sanitizeText(caption.slice(0, 160)),
          sourceMaterial: { kind: 'image', png },
        })
      }
      if (captionBeforeImage || (!inline && caption && images.some((image) => image.getAttribute('src')))) index += 1
      if (inline && !images.some((image) => image.getAttribute('src'))) addText(inline)
      continue
    }
    const copy = node.cloneNode(true) as Element
    if (node.tagName === 'LI') copy.querySelectorAll('ul,ol,p').forEach((child) => child.remove())
    const text = compact(copy.textContent)
    if (/^H[1-6]$/.test(node.tagName) && text) {
      flush()
      heading = sanitizeText(text.slice(0, 200))
    } else {
      addText(text)
    }
  }
  flush()
  if (slides.length === 1) throw new FileImportError('В DOCX нет текста, таблиц или поддерживаемых изображений.')
  const warnings = [
    ...(omittedImages ? [`Пропущено изображений: ${omittedImages}. Поддерживаются PNG и JPEG в пределах размера импорта.`] : []),
    ...(flattenedTables ? [`Таблиц перенесено текстом из-за сложной структуры: ${flattenedTables}.`] : []),
  ]
  return { presentation: presentationSchema.parse({ title, slides }), warnings }
}
