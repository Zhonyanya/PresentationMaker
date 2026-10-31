/**
 * Чтение исходного текста из файла прямо в браузере.
 * TXT — с автоопределением кодировки (UTF-8 / Windows-1251),
 * DOCX — через mammoth, с сохранением заголовков и списков.
 */

export const ACCEPTED_FILE_TYPES = '.txt,.md,.docx,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const MAX_FILE_SIZE = 10 * 1024 * 1024
/**
 * Предел распакованного содержимого DOCX без картинок. Сжатый файл в пару мегабайт
 * может распаковаться в гигабайт («zip-бомба») и уронить вкладку, поэтому размер
 * частей проверяется до разбора документа.
 */
const MAX_DOCX_UNPACKED = 30 * 1024 * 1024
const UNREADABLE = 'Не удалось прочитать документ. Проверьте, что файл не повреждён, или скопируйте текст вручную.'

export class FileImportError extends Error {}

import { sanitizeText } from './text'

export async function readSourceFile(file: File): Promise<string> {
  return sanitizeText(await readRaw(file))
}

async function readRaw(file: File): Promise<string> {
  if (file.size > MAX_FILE_SIZE) throw new FileImportError('Файл больше 10 МБ. Вставьте нужный фрагмент текста вручную.')
  const name = file.name.toLowerCase()

  if (name.endsWith('.docx')) return readDocx(file)
  if (name.endsWith('.doc')) {
    throw new FileImportError('Старый формат .doc не поддерживается. Сохраните документ как .docx или скопируйте текст.')
  }
  if (name.endsWith('.txt') || name.endsWith('.md') || file.type.startsWith('text/')) return readText(file)
  throw new FileImportError('Поддерживаются файлы .txt, .md и .docx.')
}

/** Расшифровывает текстовый файл: UTF-8, UTF-16 с BOM или Windows-1251. */
export function decodeText(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder('utf-16le').decode(bytes)
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder('utf-16be').decode(bytes)
  // ZIP (например, .docx с расширением .txt) или бинарный файл: в тексте нулевых байтов не бывает
  const sample = bytes.subarray(0, 8192)
  const zip = bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04
  if (zip || sample.filter((b) => b === 0).length > sample.length / 100) {
    throw new FileImportError('Файл не похож на текстовый. Сохраните документ как .txt или .docx.')
  }
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
  } catch {
    // Недопустимые для UTF-8 последовательности — почти всегда Windows-1251 из старого Блокнота
    return new TextDecoder('windows-1251').decode(bytes)
  }
}

async function readText(file: File): Promise<string> {
  return decodeText(await file.arrayBuffer())
}

/** Отклоняет DOCX, который при распаковке займёт слишком много памяти. */
async function assertUnpackedSize(buffer: ArrayBuffer) {
  const JSZip = (await import('jszip')).default
  let zip: InstanceType<typeof JSZip>
  try {
    zip = await JSZip.loadAsync(buffer)
  } catch {
    throw new FileImportError(UNREADABLE)
  }
  const tooLarge = () => new FileImportError('Документ слишком большой после распаковки. Вставьте нужный фрагмент текста вручную.')
  // Картинки не распаковываются: текст из них не нужен
  const entries = Object.values(zip.files).filter((entry) => !entry.dir && !entry.name.startsWith('word/media/'))
  // Быстрая проверка по размерам из заголовков архива
  let declared = 0
  for (const entry of entries) declared += (entry as unknown as { _data?: { uncompressedSize?: number } })._data?.uncompressedSize ?? 0
  if (declared > MAX_DOCX_UNPACKED) throw tooLarge()
  // Заголовки можно подделать, поэтому считаем реально распакованные байты потоком
  // и останавливаемся, как только бюджет исчерпан
  let total = 0
  for (const entry of entries) {
    total += await inflatedSize(entry as unknown as StreamableEntry, MAX_DOCX_UNPACKED - total)
    if (total > MAX_DOCX_UNPACKED) throw tooLarge()
  }
}

/** Часть публичного API JSZip, не описанная в его типах */
interface StreamableEntry {
  internalStream(type: 'uint8array'): {
    on(event: 'data', listener: (chunk: Uint8Array) => void): unknown
    on(event: 'error', listener: (error: Error) => void): unknown
    on(event: 'end', listener: () => void): unknown
    pause(): unknown
    resume(): unknown
  }
}

/** Сколько байт даёт распаковка части архива — не больше budget + один фрагмент. */
function inflatedSize(entry: StreamableEntry, budget: number): Promise<number> {
  return new Promise((resolve, reject) => {
    let size = 0
    const stream = entry.internalStream('uint8array')
    stream.on('data', (chunk) => {
      size += chunk.length
      if (size > budget) {
        stream.pause()
        resolve(size)
      }
    })
    stream.on('error', () => reject(new FileImportError(UNREADABLE)))
    stream.on('end', () => resolve(size))
    stream.resume()
  })
}

async function readDocx(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  await assertUnpackedSize(buffer)
  try {
    const mammoth = await import('mammoth')
    const { value: html } = await mammoth.convertToHtml(
      { arrayBuffer: buffer },
      // Картинки не читаем вовсе: иначе mammoth встраивает их в HTML как base64
      { convertImage: mammoth.images.imgElement(async () => ({ src: '' })) },
    )
    return htmlToStructuredText(html)
  } catch (error) {
    console.error('[file-import] DOCX', error)
    throw new FileImportError(UNREADABLE)
  }
}

/** Текст узла без вложенных списков: у пункта со вложенным списком подпункты идут отдельными строками */
function ownText(node: Element): string {
  const copy = node.cloneNode(true) as Element
  copy.querySelectorAll('ul, ol').forEach((list) => list.remove())
  return copy.textContent?.replace(/\s+/g, ' ').trim() ?? ''
}

/** Заголовки → «# …», пункты списков → «- …», абзацы → строки через пустую строку. */
export function htmlToStructuredText(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const lines: string[] = []
  doc.body.querySelectorAll('h1, h2, h3, h4, h5, h6, p, li').forEach((node) => {
    const tag = node.tagName.toLowerCase()
    // Абзац внутри пункта списка уже вошёл в текст пункта
    if (tag !== 'li' && node.closest('li')) return
    const text = ownText(node)
    if (!text) return
    if (tag === 'li') lines.push(`- ${text}`)
    else if (tag.startsWith('h')) lines.push('', `${'#'.repeat(Math.min(Number(tag[1]), 2))} ${text}`)
    else lines.push(text, '')
  })
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
