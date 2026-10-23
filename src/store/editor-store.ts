import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { presentationSchema, type Presentation, type Slide, type SlideLayout } from '@/domain/presentation'
import * as ops from '@/domain/operations'
import { safeStorage } from '@/lib/storage'

interface EditorState {
  presentation: Presentation | null
  selectedId: string | null
  savedAt: string | null
  /** Меняется при загрузке или закрытии презентации — отложенные «Отменить» к другой презентации не применяются */
  session: number

  load: (presentation: Presentation) => void
  close: () => void
  select: (id: string) => void
  selectByOffset: (delta: number) => void
  setTitle: (title: string) => void
  updateSlide: (id: string, patch: Partial<Slide>) => void
  /** Возвращает слайд до изменения — для «Отменить» */
  changeLayout: (id: string, layout: SlideLayout) => { previous: Slide; converted: Slide } | null
  replaceSlide: (slide: Slide) => void
  addSlide: (layout: SlideLayout, afterId?: string | null) => string
  duplicateSlide: (id: string) => void
  /** Возвращает удалённый слайд и его позицию — для «Отменить» */
  removeSlide: (id: string) => { slide: Slide; index: number } | null
  restoreSlide: (slide: Slide, index: number) => void
  moveSlide: (fromIndex: number, toIndex: number) => void
  splitSlide: (id: string) => boolean
}

const now = () => new Date().toISOString()

export const useEditorStore = create<EditorState>()(
  persist(
    (set, get) => {
      /** Применяет изменение презентации и обновляет отметку автосохранения */
      const commit = (presentation: Presentation, selectedId = get().selectedId) =>
        set({ presentation, selectedId, savedAt: now() })

      return {
        presentation: null,
        selectedId: null,
        savedAt: null,
        session: 0,

        load: (presentation) =>
          set((state) => ({ presentation, selectedId: presentation.slides[0]?.id ?? null, savedAt: now(), session: state.session + 1 })),
        close: () => set((state) => ({ presentation: null, selectedId: null, savedAt: null, session: state.session + 1 })),

        select: (id) => set({ selectedId: id }),
        selectByOffset: (delta) => {
          const { presentation, selectedId } = get()
          if (!presentation) return
          const index = presentation.slides.findIndex((s) => s.id === selectedId)
          const next = presentation.slides[Math.min(Math.max(index + delta, 0), presentation.slides.length - 1)]
          if (next) set({ selectedId: next.id })
        },

        setTitle: (title) => {
          const { presentation } = get()
          if (presentation) commit({ ...presentation, title })
        },

        updateSlide: (id, patch) => {
          const { presentation } = get()
          if (presentation) commit(ops.updateSlide(presentation, id, patch))
        },

        changeLayout: (id, layout) => {
          const { presentation } = get()
          const slide = presentation?.slides.find((s) => s.id === id)
          if (!presentation || !slide || slide.layout === layout) return null
          const converted = ops.convertSlide(slide, layout)
          commit(ops.replaceSlide(presentation, converted))
          return { previous: slide, converted }
        },

        replaceSlide: (slide) => {
          const { presentation } = get()
          if (presentation) commit(ops.replaceSlide(presentation, slide))
        },

        addSlide: (layout, afterId) => {
          const { presentation, selectedId } = get()
          const slide = ops.createSlide(layout)
          if (!presentation) return slide.id
          const anchor = afterId ?? selectedId
          const index = presentation.slides.findIndex((s) => s.id === anchor)
          commit(ops.insertSlide(presentation, slide, index === -1 ? presentation.slides.length : index + 1), slide.id)
          return slide.id
        },

        duplicateSlide: (id) => {
          const { presentation } = get()
          if (!presentation) return
          const result = ops.duplicateSlide(presentation, id)
          if (result.newId) commit(result.presentation, result.newId)
        },

        removeSlide: (id) => {
          const { presentation, selectedId } = get()
          if (!presentation || presentation.slides.length <= 1) return null
          const index = presentation.slides.findIndex((s) => s.id === id)
          if (index === -1) return null
          const slide = presentation.slides[index]
          const next = ops.removeSlide(presentation, id)
          const neighbour = next.slides[Math.min(index, next.slides.length - 1)]
          commit(next, selectedId === id ? neighbour.id : selectedId)
          return { slide, index }
        },

        restoreSlide: (slide, index) => {
          const { presentation } = get()
          if (!presentation || presentation.slides.some((s) => s.id === slide.id)) return
          commit(ops.insertSlide(presentation, slide, index), slide.id)
        },

        moveSlide: (fromIndex, toIndex) => {
          const { presentation } = get()
          if (presentation && fromIndex !== toIndex) commit(ops.moveSlide(presentation, fromIndex, toIndex))
        },

        splitSlide: (id) => {
          const { presentation } = get()
          if (!presentation) return false
          const result = ops.splitSlide(presentation, id)
          if (!result.newId) return false
          commit(result.presentation, result.newId)
          return true
        },
      }
    },
    {
      name: 'ai-presentations:draft:v1',
      version: 1,
      storage: createJSONStorage(() => safeStorage),
      partialize: ({ presentation, selectedId, savedAt }) => ({ presentation, selectedId, savedAt }),
      // Повреждённый или устаревший черновик не должен ломать приложение
      merge: (persisted, current) => {
        const state = persisted as Partial<EditorState> | undefined
        const parsed = presentationSchema.safeParse(state?.presentation)
        if (!parsed.success) return current
        const selectedId = parsed.data.slides.some((s) => s.id === state?.selectedId)
          ? (state?.selectedId ?? null)
          : (parsed.data.slides[0]?.id ?? null)
        return { ...current, presentation: parsed.data, selectedId, savedAt: state?.savedAt ?? null }
      },
    },
  ),
)

export const selectSelectedSlide = (state: EditorState): Slide | null =>
  state.presentation?.slides.find((s) => s.id === state.selectedId) ?? state.presentation?.slides[0] ?? null
