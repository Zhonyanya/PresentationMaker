import type { GenerateRequest, GenerateResponse } from '@/domain/presentation'
import { splitInHalf } from '@/layouts/content-utils'
import { deriveTitle, parseSource, splitSentences, toBullet, type SourceBlock } from './text-analysis'

/**
 * ДЕМОНСТРАЦИОННЫЙ генератор структуры презентации.
 *
 * Работает без языковой модели: делит введённый текст на смысловые блоки
 * (заголовки, абзацы, списки) и раскладывает их по макетам. Формулировки
 * берутся из исходного текста; полный текст блока попадает в заметки
 * докладчика. Настоящая генерация — на сервере, через ML-модуль (см. ML_CONTRACT.md).
 */

type GeneratedSlide = GenerateResponse['slides'][number]
type Candidate =
  | { kind: 'section'; title: string; subtitle?: string }
  | { kind: 'bullets'; title: string; items: string[]; notes: string }
  | { kind: 'text'; title: string; body: string; notes: string }
  | { kind: 'columns'; title: string; leftTitle: string; left: string[]; rightTitle: string; right: string[]; notes: string }

const MAX_BULLETS = 6
const MAX_TEXT_LENGTH = 520

export function generateMockPresentation(request: GenerateRequest): GenerateResponse {
  const parsed = parseSource(request.text)
  const title = request.title?.trim() || parsed.title || deriveTitle(request.text, 8) || 'Презентация'
  const contentTarget = Math.max(1, request.slideCount - 2)

  const useSections = parsed.blocks.some((b) => b.level === 1) && parsed.blocks.some((b) => b.level === 2)
  let candidates = parsed.blocks.flatMap((block) => blockToCandidates(block, useSections))
  candidates = fitToTarget(candidates, contentTarget)

  const slides: GeneratedSlide[] = [
    {
      layout: 'title',
      title,
      subtitle: parsed.subtitle ?? (request.title && parsed.title && parsed.title !== title ? parsed.title : ''),
      caption: String(new Date().getFullYear()),
      notes: '',
    },
    ...candidates.map(candidateToSlide),
    {
      layout: 'closing',
      title: 'Спасибо за внимание',
      subtitle: title,
      notes: '',
    },
  ]
  return { title, slides: slides.map((slide, i) => ({ ...slide, id: `slide-${i + 1}` })) }
}

function blockToCandidates(block: SourceBlock, useSections: boolean): Candidate[] {
  const notes = [...block.paragraphs, ...block.items.map((i) => `• ${i}`)].join('\n')
  const hasContent = block.paragraphs.length > 0 || block.items.length > 0

  if (useSections && block.level === 1 && block.heading) {
    const section: Candidate = {
      kind: 'section',
      title: block.heading,
      subtitle: block.paragraphs[0] && block.paragraphs[0].length <= 160 ? block.paragraphs[0].replace(/\.$/, '') : undefined,
    }
    const rest: SourceBlock = {
      ...block,
      level: 2,
      paragraphs: section.subtitle ? block.paragraphs.slice(1) : block.paragraphs,
    }
    return rest.paragraphs.length || rest.items.length ? [section, ...blockToCandidates(rest, false)] : [section]
  }

  if (!hasContent) {
    return block.heading ? [{ kind: 'section', title: block.heading }] : []
  }

  // Несколько абзацев без заголовков и списков — каждый абзац отдельным слайдом
  if (!block.heading && block.items.length === 0 && block.paragraphs.length >= 2) {
    return block.paragraphs.flatMap((paragraph) =>
      blockToCandidates({ ...block, paragraphs: [paragraph], groups: [] }, false),
    )
  }

  const sentences = block.paragraphs.flatMap(splitSentences)
  const title = block.heading || deriveTitle(block.paragraphs[0] ?? block.items[0] ?? '')

  // Две группы «Проблемы: … / Решения: …» — две колонки
  if (block.groups.length === 2 && block.groups.every((g) => g.items.length > 0)) {
    const [a, b] = block.groups
    return [
      {
        kind: 'columns',
        title: block.heading || `${a.title} и ${b.title.toLowerCase()}`,
        leftTitle: a.title,
        left: a.items.slice(0, MAX_BULLETS),
        rightTitle: b.title,
        right: b.items.slice(0, MAX_BULLETS),
        notes,
      },
    ]
  }

  const result: Candidate[] = []
  const paragraphText = block.paragraphs.join('\n')

  if (block.items.length >= 2) {
    // Вводный абзац перед списком: короткий — первым пунктом, длинный — отдельным слайдом
    if (paragraphText.length > 260) {
      result.push({ kind: 'text', title, body: condenseParagraphs(block.paragraphs), notes: paragraphText })
      result.push(...chunkBullets(title, block.items, block.items.map((i) => `• ${i}`).join('\n')))
    } else {
      const lead = sentences.map((s) => toBullet(s))
      result.push(...chunkBullets(title, [...lead, ...block.items], notes))
    }
    return result
  }

  const items = [...sentences.map((s) => toBullet(s)), ...block.items]
  // Заголовок взят из первого предложения — не повторяем его первым пунктом
  if (!block.heading && items[0] === title) items.shift()
  if (paragraphText.length <= MAX_TEXT_LENGTH && sentences.length <= 3) {
    return [{ kind: 'text', title, body: paragraphText, notes: '' }]
  }
  return chunkBullets(title, items, notes)
}

function condenseParagraphs(paragraphs: string[]): string {
  const sentences = paragraphs.flatMap(splitSentences)
  let body = ''
  for (const sentence of sentences) {
    if ((body + ' ' + sentence).trim().length > MAX_TEXT_LENGTH) break
    body = (body + ' ' + sentence).trim()
  }
  return body || sentences[0]?.slice(0, MAX_TEXT_LENGTH) || ''
}

function chunkBullets(title: string, items: string[], notes: string): Candidate[] {
  const filtered = items.filter(Boolean)
  if (filtered.length <= MAX_BULLETS) return [{ kind: 'bullets', title, items: filtered, notes }]
  const chunks: string[][] = []
  for (let i = 0; i < filtered.length; i += MAX_BULLETS) chunks.push(filtered.slice(i, i + MAX_BULLETS))
  return chunks.map((chunk, i) => ({
    kind: 'bullets',
    title: i === 0 ? title : `${title} (продолжение)`,
    items: chunk,
    notes: i === 0 ? notes : '',
  }))
}

function sizeOf(candidate: Candidate): number {
  switch (candidate.kind) {
    case 'bullets':
      return candidate.items.length
    case 'text':
      return splitSentences(candidate.body).length
    case 'columns':
      return candidate.left.length + candidate.right.length
    default:
      return 0
  }
}

/** Приближает количество слайдов к запрошенному: делит крупные или объединяет мелкие соседние слайды. */
function fitToTarget(input: Candidate[], target: number): Candidate[] {
  let candidates = [...input]

  // Слишком мало слайдов — делим самые объёмные
  while (candidates.length < target) {
    let index = -1
    // Делим только действительно объёмные слайды — список из 3–5 пунктов дробить незачем
    let max = 5
    candidates.forEach((c, i) => {
      if ((c.kind === 'bullets' || c.kind === 'text') && sizeOf(c) > max) {
        max = sizeOf(c)
        index = i
      }
    })
    if (index === -1) break
    const c = candidates[index] as Extract<Candidate, { kind: 'bullets' | 'text' }>
    const [a, b] =
      c.kind === 'bullets'
        ? splitInHalf(c.items)
        : splitInHalf(splitSentences(c.body)).map((part) => part.map((x) => toBullet(x)))
    const continuation = `${c.title.replace(/ \(продолжение\)$/, '')} (продолжение)`
    candidates.splice(
      index,
      1,
      { kind: 'bullets', title: c.title, items: a, notes: c.notes || (c.kind === 'text' ? c.body : '') },
      { kind: 'bullets', title: continuation, items: b, notes: '' },
    )
  }

  // Слишком много — объединяем пары небольших соседних списков в слайд с двумя колонками
  while (candidates.length > target) {
    let best = -1
    let bestSize = Number.POSITIVE_INFINITY
    for (let i = 0; i < candidates.length - 1; i++) {
      const a = candidates[i]
      const b = candidates[i + 1]
      if (a.kind !== 'bullets' || b.kind !== 'bullets') continue
      const size = a.items.length + b.items.length
      if (size <= MAX_BULLETS + 2 && size < bestSize) {
        best = i
        bestSize = size
      }
    }
    if (best === -1) break
    const a = candidates[best] as Extract<Candidate, { kind: 'bullets' }>
    const b = candidates[best + 1] as Extract<Candidate, { kind: 'bullets' }>
    const combinedTitle = a.title.length + b.title.length <= 60 ? `${a.title} и ${lowerFirst(b.title)}` : a.title
    candidates.splice(best, 2, {
      kind: 'columns',
      title: combinedTitle,
      leftTitle: a.title,
      left: a.items,
      rightTitle: b.title,
      right: b.items,
      notes: [a.notes, b.notes].filter(Boolean).join('\n\n'),
    })
  }
  return candidates
}

function lowerFirst(text: string): string {
  // Не трогаем аббревиатуры: «ЕГЭ», «ИИ»
  if (/^[A-ZА-ЯЁ]{2,}/.test(text)) return text
  return text.charAt(0).toLowerCase() + text.slice(1)
}

function candidateToSlide(candidate: Candidate): GeneratedSlide {
  switch (candidate.kind) {
    case 'section':
      return { layout: 'section', title: candidate.title, subtitle: candidate.subtitle ?? '', notes: '' }
    case 'text':
      return { layout: 'text', title: candidate.title, body: candidate.body, notes: candidate.notes }
    case 'bullets':
      return { layout: 'bullets', title: candidate.title, bullets: candidate.items, notes: candidate.notes }
    case 'columns':
      return {
        layout: 'two-column',
        title: candidate.title,
        leftTitle: candidate.leftTitle,
        left: candidate.left,
        rightTitle: candidate.rightTitle,
        right: candidate.right,
        notes: candidate.notes,
      }
  }
}
