/** Вспомогательные функции для преобразования содержимого между макетами. */

export function splitInHalf<T>(items: T[]): [T[], T[]] {
  const middle = Math.ceil(items.length / 2)
  return [items.slice(0, middle), items.slice(middle)]
}

export function paragraphsOf(text: string | undefined): string[] {
  return (text ?? '')
    .split(/\n+/)
    .map((t) => t.trim())
    .filter(Boolean)
}

export function nonEmpty(items: string[]): string[] {
  return items.map((t) => t.trim()).filter(Boolean)
}

const sentences = new Intl.Segmenter('ru', { granularity: 'sentence' })

export function firstSentence(text: string): string {
  return sentences.segment(text).containing(0)?.segment.trim() ?? text
}

export function sentencesOf(text: string): string[] {
  const result: string[] = []
  let pending = ''
  for (const { segment } of sentences.segment(text)) {
    pending += segment
    const sentence = pending.trim()
    // The Russian segmenter can put a boundary after «им.» or Cyrillic initials.
    if (/(?:^|[\s(])(?:им\.|(?:[А-ЯЁ]\.\s*)+)$/u.test(sentence)) continue
    if (sentence) result.push(sentence)
    pending = ''
  }
  if (pending.trim()) result.push(pending.trim())
  return result
}
