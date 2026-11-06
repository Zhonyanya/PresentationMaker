import { plural } from '@/lib/utils'
import type { ApiErrorCode } from '@/api/errors'

/** Отказ ML выполнить команду правки, меняющую структуру (добавить, удалить, переставить слайды) */
export const STRUCTURE_COMMAND_MESSAGE =
  'Командой можно менять только содержание слайдов: текст, формулировки, макет. Добавлять, удалять и переставлять слайды, ' +
  'вставлять картинки и таблицы нельзя. Попробуйте, например: «сократи пункты на слайде 3». Документ не изменился.'

const FALLBACK = 'Задание завершилось с ошибкой. Предыдущий документ сохранён.'

/** Тип задания; null — неизвестен (например, после перезагрузки без сохранённых сведений) */
type JobKind = 'generate' | 'revise' | null

/**
 * Текст ошибки завершённого задания и можно ли предложить перечитать документ.
 *
 * ML_CAPABILITY_UNAVAILABLE сервер отдаёт и на структурную команду правки, и когда
 * ML-модуль настроен не полностью. Подсказка про команды уместна только для правки:
 * при генерации или неизвестном типе показываем сообщение сервера как есть.
 */
export function jobFailure(error: { code: string; message: string } | null | undefined, kind: JobKind): { message: string; canRefresh: boolean } {
  if (error?.code === 'ML_CAPABILITY_UNAVAILABLE' && kind === 'revise') return { message: STRUCTURE_COMMAND_MESSAGE, canRefresh: false }
  return { message: error?.message || FALLBACK, canRefresh: true }
}

/** Что делать с ожиданием, когда запрос статуса задания не удался. */
export type PollFailure = 'retry' | 'pause' | 'drop'

/** Сбои, при которых задание продолжает выполняться на сервере, а запрос стоит повторить */
const TRANSIENT = new Set<ApiErrorCode>(['network', 'timeout', 'server', 'rate_limited'])

/**
 * Временный сбой повторяем, пока не кончатся попытки, затем ставим ожидание на паузу:
 * задание, скорее всего, ещё идёт; истёкшая сессия — тоже не повод забывать задание.
 * Прочие ошибки (задание не найдено, доступ закрыт, ответ не по контракту) повтором
 * не исправить — такое задание больше не отслеживаем, чтобы оно не блокировало
 * новую работу до перезагрузки страницы.
 */
export function pollFailure(code: ApiErrorCode, failures: number, retries: number): PollFailure {
  if (code === 'unauthorized') return 'pause'
  if (!TRANSIENT.has(code)) return 'drop'
  return failures < retries ? 'retry' : 'pause'
}

/**
 * Пояснение, если слайдов получилось меньше запрошенного: ML-модуль может вернуть
 * меньше слайдов, когда в коротком тексте не хватает материала на запрошенное число.
 */
export function slideShortfall(current: { requested_slide_count: number; slide_count: number | null } | null | undefined): string | null {
  const actual = current?.slide_count
  if (!current || !actual || actual >= current.requested_slide_count) return null
  const requested = current.requested_slide_count
  return (
    `Получилось ${actual} ${plural(actual, ['слайд', 'слайда', 'слайдов'])} вместо ${requested}: ` +
    'похоже, в тексте не нашлось материала на большее. ' +
    'Чтобы слайдов было больше, добавьте материал и запустите полную перегенерацию.'
  )
}
