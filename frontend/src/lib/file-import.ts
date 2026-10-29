/**
 * Чтение исходного текста из файла прямо в браузере.
 * TXT — с автоопределением кодировки (UTF-8 / Windows-1251),
 * DOCX — через mammoth, с сохранением заголовков и списков.
 */

export const ACCEPTED_FILE_TYPES = '.txt,.md,.docx,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const MAX_FILE_SIZE = 10 * 1024 * 1024

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
  throw new FileImportError('Поддерживаются файлы .txt и .docx.')
}

async function readText(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  const utf8 = new TextDecoder('utf-8').decode(buffer)
  // Символы-заменители — признак, что файл не в UTF-8 (часто Windows-1251)
  if (!utf8.includes('�')) return utf8
  try {
    return new TextDecoder('windows-1251').decode(buffer)
  } catch {
    return utf8
  }
}

async function readDocx(file: File): Promise<string> {
  try {
    const mammoth = await import('mammoth')
    const { value: html } = await mammoth.convertToHtml({ arrayBuffer: await file.arrayBuffer() })
    return htmlToStructuredText(html)
  } catch (error) {
    console.error('[file-import] DOCX', error)
    throw new FileImportError('Не удалось прочитать документ. Проверьте, что файл не повреждён, или скопируйте текст вручную.')
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
