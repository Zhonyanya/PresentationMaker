/**
 * Простые эвристики для демонстрационного генератора.
 * Настоящую структуру и формулировки будет строить языковая модель на бэкенде.
 */

export interface SourceBlock {
  heading?: string
  /** 1 — раздел верхнего уровня, 2 — подраздел */
  level: 1 | 2
  paragraphs: string[]
  items: string[]
  /** Подсписки вида «Проблемы:» + пункты — кандидаты на две колонки */
  groups: { title: string; items: string[] }[]
}

export interface ParsedSource {
  title?: string
  subtitle?: string
  blocks: SourceBlock[]
}

const BULLET_RE = /^(?:[-–—•*·▪●◦]|[а-яa-z]\)|\d{1,2}\.\d{1,2}\.?)\s+(.+)$/i
const NUMBERED_RE = /^(?:\d{1,2}|[IVXLC]{1,5})[.)]\s+(.+)$/
const ROMAN_RE = /^[IVXLC]{1,5}[.)]\s+/
const MARKDOWN_HEADING_RE = /^(#{1,6})\s+(.+)$/
const SECTION_WORD_RE = /^(раздел|часть|глава)\s+\S+/i
const TERMINAL_PUNCTUATION_RE = /[.!?;…]$/
// «т. д.», «т. п.», «и др.» обычно стоят в конце предложения — их здесь нет
const ABBREVIATIONS = new Set(['т', 'г', 'гг', 'пр', 'им', 'ст', 'тыс', 'млн', 'млрд', 'руб', 'т.е', 'т.д', 'т.п', 'см', 'н', 'э', 'в', 'вв', 'ул', 'обл'])

import { sanitizeText } from '@/lib/text'

export function normalizeText(raw: string): string {
  return sanitizeText(raw)
    .replace(/\r\n?/g, '\n')
    .replace(/ /g, ' ')
    .replace(/\t/g, ' ')
    .replace(/[ ]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function cleanHeading(text: string): string {
  return text
    .replace(MARKDOWN_HEADING_RE, '$2')
    .replace(NUMBERED_RE, '$1')
    .replace(/[:：]\s*$/, '')
    .replace(/\*\*/g, '')
    .trim()
}

function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}

function isAllCaps(text: string): boolean {
  const letters = text.replace(/[^A-Za-zА-Яа-яЁё]/g, '')
  return letters.length >= 4 && letters === letters.toUpperCase()
}

function looksLikeHeading(line: string, next: string | undefined): boolean {
  if (line.length > 90 || wordCount(line) > 12) return false
  if (TERMINAL_PUNCTUATION_RE.test(line)) return false
  if (line.endsWith(',')) return false
  return next !== undefined && next.trim() !== ''
}

function headingLevel(line: string): 1 | 2 {
  const md = line.match(MARKDOWN_HEADING_RE)
  if (md) return md[1].length <= 1 ? 1 : 2
  if (ROMAN_RE.test(line) || SECTION_WORD_RE.test(line) || isAllCaps(line)) return 1
  return 2
}

/** Делит текст на смысловые блоки: заголовок + абзацы + пункты списков. */
export function parseSource(raw: string): ParsedSource {
  const lines = normalizeText(raw).split('\n').map((l) => l.trim())
  const blocks: SourceBlock[] = []
  let current: SourceBlock = { level: 2, paragraphs: [], items: [], groups: [] }
  let paragraphBuffer: string[] = []
  let activeGroup: { title: string; items: string[] } | null = null

  const flushParagraph = () => {
    if (paragraphBuffer.length) {
      current.paragraphs.push(paragraphBuffer.join(' '))
      paragraphBuffer = []
    }
  }
  const startBlock = (heading: string, level: 1 | 2) => {
    flushParagraph()
    activeGroup = null
    if (current.heading || current.paragraphs.length || current.items.length) blocks.push(current)
    current = { heading, level, paragraphs: [], items: [], groups: [] }
  }

  lines.forEach((line, index) => {
    const next = lines.slice(index + 1).find((l) => l !== '')
    if (line === '') {
      flushParagraph()
      return
    }

    const markdown = line.match(MARKDOWN_HEADING_RE)
    if (markdown) {
      startBlock(cleanHeading(line), headingLevel(line))
      return
    }

    const bullet = line.match(BULLET_RE)
    if (bullet) {
      flushParagraph()
      const item = bullet[1].trim()
      current.items.push(item)
      if (activeGroup) activeGroup.items.push(item)
      return
    }

    const numbered = line.match(NUMBERED_RE)
    if (numbered) {
      const content = numbered[1].trim()
      // Короткий пункт без точки в плане выступления — заголовок раздела
      const isHeading = content.length <= 90 && !TERMINAL_PUNCTUATION_RE.test(content) && next !== undefined && !NUMBERED_RE.test(next)
      if (isHeading) {
        startBlock(cleanHeading(line), headingLevel(line))
      } else {
        flushParagraph()
        current.items.push(content.replace(/[.;]$/, ''))
      }
      return
    }

    // «Проблемы:» перед списком — начало группы
    if (/[:：]$/.test(line) && line.length <= 80 && next && BULLET_RE.test(next)) {
      flushParagraph()
      activeGroup = { title: cleanHeading(line), items: [] }
      current.groups.push(activeGroup)
      return
    }

    if ((isAllCaps(line) && line.length <= 90) || (looksLikeHeading(line, next) && paragraphBuffer.length === 0)) {
      startBlock(cleanHeading(line), headingLevel(line))
      return
    }

    activeGroup = null
    paragraphBuffer.push(line)
  })
  flushParagraph()
  if (current.heading || current.paragraphs.length || current.items.length) blocks.push(current)

  // Название документа: первый заголовок без содержимого или единственный заголовок в тексте
  let title: string | undefined
  let subtitle: string | undefined
  const first = blocks[0]
  const headingCount = blocks.filter((b) => b.heading).length
  const firstIsEmpty = first?.heading && first.paragraphs.length === 0 && first.items.length === 0
  if (first?.heading && (firstIsEmpty || headingCount === 1)) {
    title = first.heading
    first.heading = undefined
    if (firstIsEmpty) {
      blocks.shift()
      // Следующий короткий заголовок без содержимого — подзаголовок («Доклад на коллегии»)
      const next = blocks[0]
      if (next?.heading && next.paragraphs.length === 0 && next.items.length === 0 && next.heading.length <= 160) {
        subtitle = next.heading
        blocks.shift()
      }
    }
  }

  return { title, subtitle, blocks: blocks.filter((b) => b.paragraphs.length || b.items.length || b.heading) }
}

/** Разбивка на предложения с учётом частых сокращений. */
export function splitSentences(text: string): string[] {
  const result: string[] = []
  let start = 0
  const re = /[.!?…]+["»)]?\s+(?=[«"(]?[А-ЯЁA-Z0-9])/g
  let match: RegExpExecArray | null
  while ((match = re.exec(text))) {
    const before = text.slice(start, match.index)
    const lastWord = before.split(/\s+/).pop()?.toLowerCase().replace(/[^a-zа-яё.]/g, '') ?? ''
    if (ABBREVIATIONS.has(lastWord) || /^[а-яё]\.[а-яё]$/.test(lastWord)) continue
    result.push(text.slice(start, match.index + match[0].trimEnd().length).trim())
    start = match.index + match[0].length
  }
  const tail = text.slice(start).trim()
  if (tail) result.push(tail)
  return result
}

const LEADING_CONNECTIVES =
  /^(кроме того|также|при этом|таким образом|в частности|в том числе|вместе с тем|в связи с этим|следует отметить, что|необходимо отметить, что|важно отметить, что|отдельно отмечу, что|хочу отметить, что|в результате|в итоге|прежде всего|во-первых|во-вторых|в-третьих|и наконец|наконец|итак)[,:]?\s+/i

/** Превращает предложение в пункт списка: без вводных слов и финальной точки, не длиннее limit. */
export function toBullet(sentence: string, limit = 200): string {
  let text = sentence.trim().replace(LEADING_CONNECTIVES, '')
  text = text.charAt(0).toUpperCase() + text.slice(1)
  if (text.length > limit) {
    const slice = text.slice(0, limit)
    const cut = Math.max(slice.lastIndexOf('; '), slice.lastIndexOf(', '), slice.lastIndexOf(' — '))
    text = cut > limit * 0.5 ? slice.slice(0, cut) : slice.slice(0, slice.lastIndexOf(' '))
  }
  return text.replace(/[.;,:]+$/, '').trim()
}

/** Короткий заголовок из первого предложения. */
export function deriveTitle(text: string, maxWords = 9): string {
  const firstSentence = (splitSentences(text)[0] ?? text).replace(LEADING_CONNECTIVES, '')
  const clause = firstSentence.split(/[:;—–]|,\s/)[0].trim()
  const words = clause.split(/\s+/).filter(Boolean)
  const title = words.length <= maxWords ? clause : words.slice(0, maxWords).join(' ')
  const cleaned = title.replace(/[.,;:!?]+$/, '')
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}
