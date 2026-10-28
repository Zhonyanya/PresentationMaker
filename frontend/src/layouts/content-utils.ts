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
