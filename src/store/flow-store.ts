import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { ApiError, presentationApi, type GenerationStageId } from '@/api'
import { toApiError } from '@/api/errors'
import { LIMITS, type GenerateRequest } from '@/domain/presentation'
import { safeStorage } from '@/lib/storage'
import { useEditorStore } from './editor-store'

export type View = 'create' | 'generating' | 'editor'

export interface SourceDraft {
  text: string
  title: string
  slideCount: number
}

interface GenerationState {
  status: 'idle' | 'running' | 'error'
  stage: GenerationStageId | null
  completedStages: GenerationStageId[]
  error: ApiError | null
  startedAt: number | null
}

interface FlowState {
  view: View
  draft: SourceDraft
  generation: GenerationState
  setDraft: (patch: Partial<SourceDraft>) => void
  clearDraft: () => void
  generate: () => Promise<void>
  cancel: () => void
  openEditor: () => void
  backToCreate: () => void
}

const idleGeneration: GenerationState = { status: 'idle', stage: null, completedStages: [], error: null, startedAt: null }
const emptyDraft: SourceDraft = { text: '', title: '', slideCount: LIMITS.slideCountDefault }

let controller: AbortController | null = null

export const useFlowStore = create<FlowState>()(
  persist(
    (set, get) => ({
      view: 'create',
      draft: emptyDraft,
      generation: idleGeneration,

      setDraft: (patch) => set((state) => ({ draft: { ...state.draft, ...patch } })),
      clearDraft: () => set((state) => ({ draft: { ...emptyDraft, slideCount: state.draft.slideCount } })),

      generate: async () => {
        controller?.abort()
        const current = new AbortController()
        controller = current
        const { draft } = get()
        const request: GenerateRequest = {
          text: draft.text,
          title: draft.title.trim() || undefined,
          slideCount: draft.slideCount,
        }
        set({ view: 'generating', generation: { ...idleGeneration, status: 'running', startedAt: Date.now() } })

        try {
          const presentation = await presentationApi.generate(request, {
            signal: current.signal,
            onStage: (stage) =>
              set((state) => {
                const previous = state.generation.stage
                return {
                  generation: {
                    ...state.generation,
                    stage,
                    completedStages: previous ? [...state.generation.completedStages, previous] : state.generation.completedStages,
                  },
                }
              }),
          })
          if (controller !== current) return
          useEditorStore.getState().load(presentation)
          set({ view: 'editor', generation: idleGeneration })
        } catch (error) {
          if (controller !== current) return
          const apiError = toApiError(error)
          if (apiError.code === 'aborted') {
            set({ view: 'create', generation: idleGeneration })
            return
          }
          console.error('[generate]', apiError.code, apiError.details ?? apiError)
          set((state) => ({ generation: { ...state.generation, status: 'error', error: apiError } }))
        } finally {
          if (controller === current) controller = null
        }
      },

      cancel: () => {
        controller?.abort()
        controller = null
        set({ view: 'create', generation: idleGeneration })
      },

      openEditor: () => set({ view: 'editor' }),
      backToCreate: () => set({ view: 'create', generation: idleGeneration }),
    }),
    {
      name: 'ai-presentations:source:v1',
      storage: createJSONStorage(() => safeStorage),
      // Исходный текст и открытый редактор переживают обновление страницы.
      // Незавершённая генерация — нет: после перезагрузки возвращаемся к тексту.
      partialize: ({ draft, view }) => ({ draft, view: view === 'editor' ? view : 'create' }),
    },
  ),
)
