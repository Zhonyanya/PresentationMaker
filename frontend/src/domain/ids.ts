let counter = 0

/** Короткий уникальный идентификатор слайда. */
export function createId(prefix = 'slide'): string {
  counter += 1
  const random =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10)
  return `${prefix}-${random}${counter.toString(36)}`
}
