import type { GenerateRequest, Presentation } from '@/domain/presentation'
import type { ApiMode } from '@/config/env'

/**
 * Этапы генерации. В демо-режиме они имитируются по таймеру.
 * Настоящий бэкенд может сообщать этапы, если перейдёт на потоковую
 * передачу (см. BACKEND_INTEGRATION.md, «Прогресс генерации»).
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
  /** Вызывается, если реализация API умеет сообщать этап. HTTP-клиент по умолчанию — не умеет. */
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
