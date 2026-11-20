import { imageSize } from 'image-size'
import { presentationSchema, type Presentation, type TextSlide } from '@/domain/presentation'
import { readDocxTableGrid, splitDocxTable } from './docx-table'
import { FileImportError, readDocxHtml } from './file-import'
import { sanitizeText } from './text'

const MAX_SLIDES = 60
const MAX_IMAGE_URL = 1_500_000
const IMAGE_TYPES = new Set(['image/png', 'image/jpeg'])
const CAPTION = /^(?:рисунок|рис\.|диаграмма|схема|график|figure|fig\.|chart)\s*(?:№\s*)?\d+/iu
const TABLE_CAPTION = /^(?:таблица|table)\s*(?:№\s*)?\d+/iu
const MAX_BODY = 550
const IMAGE_LOCATOR = 'data:,'

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

function blockImages(node: Element): Element[] {
  return [...node.querySelectorAll('img')].filter((img) => img.closest('p,li') === node)
}

function associateCaptions(blocks: Element[]) {
  const captions = new Map<Element, string>()
  const consumed = new Set<Element>()
  for (const [index, block] of blocks.entries()) {
    const table = block.tagName === 'TABLE'
    if (!table && !blockImages(block).some((image) => image.getAttribute('src'))) continue
    const candidates = table ? [blocks[index - 1], blocks[index + 1]] : [blocks[index + 1], blocks[index - 1]]
    for (const candidate of candidates) {
      if (candidate?.tagName !== 'P' || consumed.has(candidate) || candidate.querySelector('img')) continue
      const text = compact(candidate.textContent)
      const explicitlyNumbered = (table ? TABLE_CAPTION : CAPTION).test(text)
      const otherKind = (table ? CAPTION : TABLE_CAPTION).test(text)
      if (!text || !(explicitlyNumbered || (candidate.classList.contains('docx-caption') && !otherKind))) continue
      captions.set(block, text)
      consumed.add(candidate)
      break
    }
  }
  return { captions, consumed }
}

type DocxBlock =
  | { id: string; kind: 'text'; text: string; heading: boolean }
  | { id: string; kind: 'table'; rows: string[][]; caption: string; number?: string;
      grid: ReturnType<typeof readDocxTableGrid>;
      parts: ReturnType<typeof splitDocxTable> }
  | { id: string; kind: 'illustration'; locator: string; caption: string; png: string }

export async function readDocxSource(file: File, { preview = true } = {}) {
  let omittedImages = 0
  let mediaBytes = 0
  const html = await readDocxHtml(file, async (image) => {
    if (!preview) return { src: IMAGE_LOCATOR }
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
  }, preview)
  const document = new DOMParser().parseFromString(html, 'text/html')
  const nodes = [...document.body.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,table')]
    .filter((node) => node.tagName === 'TABLE' ? !node.parentElement?.closest('table') : !node.closest('table'))
  const { captions, consumed } = associateCaptions(nodes)
  const blocks: DocxBlock[] = []
  for (const [index, node] of nodes.entries()) {
    if (consumed.has(node)) continue
    const id = `docx-${index + 1}`
    const caption = captions.get(node) ?? ''
    if (node.tagName === 'TABLE') {
      const table = node as HTMLTableElement
      const rows = Array.from(table.rows, (row) =>
        Array.from(row.cells, (cell) => sanitizeText(cell.textContent ?? '')))
      const number = caption.match(/^(?:таблица|table)\s*(?:№\s*)?(\d+)\b/iu)?.[1]
      const grid = readDocxTableGrid(table)
      blocks.push({ id, kind: 'table', rows, caption, number, grid, parts: preview && grid ? splitDocxTable(table, grid) : [] })
      continue
    }
    const images = blockImages(node)
    if (images.length) {
      const inline = compact(node.textContent)
      let added = false
      for (const [imageIndex, image] of images.entries()) {
        const png = image.getAttribute('src')
        if (!png || (preview ? !png.startsWith('data:image/png;base64,') : png !== IMAGE_LOCATOR)) continue
        const locator = `${id}-image-${imageIndex + 1}`
        blocks.push({ id: locator, kind: 'illustration', locator, caption: [inline, caption].filter(Boolean).join(' '), png })
        added = true
      }
      const description = [inline, caption].filter(Boolean).join(' ')
      if (!added && description) blocks.push({ id, kind: 'text', text: description, heading: false })
      continue
    }
    const copy = node.cloneNode(true) as Element
    if (node.tagName === 'LI') copy.querySelectorAll('ul,ol,p').forEach((child) => child.remove())
    const text = compact(copy.textContent)
    if (text) blocks.push({ id, kind: 'text', text, heading: /^H[1-6]$/.test(node.tagName) })
  }
  return { blocks, omittedImages }
}

/** Serializable evidence input without preview images or slide-specific table parts. */
export function docxEvidenceBlocks(blocks: DocxBlock[]) {
  return blocks.map((block) => {
    const { id, kind } = block
    if (block.kind === 'text') return { id, kind, text: block.text }
    if (block.kind === 'illustration') return { id, kind, locator: block.locator, caption: block.caption }
    const rows: (string | null)[][] = (block.grid?.rows ?? block.rows).map((row) => [...row])
    for (const merge of block.grid?.merges ?? []) {
      for (let r = merge.row; r < merge.row + merge.rowspan; r += 1) {
        for (let c = merge.column; c < merge.column + merge.colspan; c += 1) {
          if (r !== merge.row || c !== merge.column) rows[r][c] = null
        }
      }
    }
    return { id, kind, rows, number: block.number, caption: block.caption, comparable: Boolean(block.grid) }
  })
}

export async function importDocxPresentation(file: File): Promise<{ presentation: Presentation; warnings: string[] }> {
  const { blocks, omittedImages } = await readDocxSource(file)
  let flattenedTables = 0
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
  for (const block of blocks) {
    if (block.kind === 'table') {
      flush()
      const { parts } = block
      const caption = sanitizeText((block.caption || 'Таблица').slice(0, 180))
      if (parts.length) {
        parts.forEach((material, part) => add({
          title: parts.length > 1 ? `${caption} · ${part + 1}/${parts.length}` : caption,
          body: '', sourceMaterial: { kind: 'table', ...material },
        }))
      } else {
        flattenedTables += 1
        if (block.caption) addText(block.caption)
        for (const row of block.rows) addText(row.map(compact).filter(Boolean).join(' · '))
        flush()
      }
      continue
    }
    if (block.kind === 'illustration') {
      flush()
      add({
        title: 'Иллюстрация', body: sanitizeText(block.caption.slice(0, 160)),
        sourceMaterial: { kind: 'image', png: block.png },
      })
      continue
    }
    if (block.heading) {
      flush()
      heading = sanitizeText(block.text.slice(0, 200))
    } else {
      addText(block.text)
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
