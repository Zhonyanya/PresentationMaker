import { plural } from '@/lib/utils'

/** Ответ ML на команду, меняющую структуру (добавить, удалить, переставить слайды) */
export const STRUCTURE_COMMAND_MESSAGE =
  'Командой можно менять только содержание слайдов: текст, формулировки, макет. Добавлять, удалять и переставлять слайды, ' +
  'вставлять картинки и таблицы нельзя. Попробуйте, например: «сократи пункты на слайде 3». Документ не изменился.'

const FALLBACK = 'Задание завершилось с ошибкой. Предыдущий документ сохранён.'

/** Текст ошибки завершённого задания: известные коды ML объясняются, что делать дальше. */
export function jobErrorMessage(error: { code: string; message: string } | null | undefined): string {
  if (error?.code === 'ML_CAPABILITY_UNAVAILABLE') return STRUCTURE_COMMAND_MESSAGE
  return error?.message || FALLBACK
}

/**
 * Пояснение, если слайдов получилось меньше запрошенного. ML не досочиняет
 * содержание, которого нет в докладе, поэтому короткий текст даёт меньше слайдов.
 */
export function slideShortfall(current: { requested_slide_count: number; slide_count: number | null } | null | undefined): string | null {
  const actual = current?.slide_count
  if (!current || !actual || actual >= current.requested_slide_count) return null
  const requested = current.requested_slide_count
  return (
    `Получилось ${actual} ${plural(actual, ['слайд', 'слайда', 'слайдов'])} вместо ${requested}: ` +
    'в тексте не нашлось материала на большее, а ML-модуль не досочиняет то, чего нет в докладе. ' +
    'Чтобы слайдов было больше, добавьте материал и запустите полную перегенерацию.'
  )
}
