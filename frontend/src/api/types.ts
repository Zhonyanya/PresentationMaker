import type { GenerateRequest, Presentation } from '@/domain/presentation'
import type { ApiMode } from '@/config/env'

/**
 * Этапы генерации демо-режима — имитируются по таймеру. Сервер сообщает
 * свои фазы задания отдельно (waiting → ml → validation → saving, см. README).
 */
export const GENERATION_STAGES = [
  { id: 'analyze', label: 'Анализируем материал' },
  { id: 'structure', label: 'Формируем структуру' },
  { id: 'content', label: 'Подготавливаем содержание' },
  { id: 'slides', label: 'Создаём слайды' },
  { id: 'design', label: 'Завершаем оформление' },
] as const

export type GenerationStageId = (typeof GENERATION_STAGES)[number]['id']

export interface GenerateOptions {
  signal?: AbortSignal
  /** Вызывается, если реализация API умеет сообщать этап. */
  onStage?: (stage: GenerationStageId) => void
}

/**
 * Единственная точка, через которую интерфейс общается с генератором.
 * Компоненты не знают, mock это или настоящий сервер.
 */
export interface PresentationApi {
  readonly mode: ApiMode
  /** true — реализация сообщает этапы через onStage */
  readonly reportsStages: boolean
  generate(request: GenerateRequest, options?: GenerateOptions): Promise<Presentation>
}
