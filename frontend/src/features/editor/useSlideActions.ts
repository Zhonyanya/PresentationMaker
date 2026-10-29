import { useCallback } from 'react'
import { toast } from 'sonner'
import type { SlideLayout } from '@/domain/presentation'
import { MAX_SLIDES } from '@/domain/operations'
import { getLayout } from '@/layouts/registry'
import { useEditorStore } from '@/store/editor-store'

/** Уведомления с «Отменить» живут дольше — чтобы успеть нажать */
const UNDO_TOAST_MS = 8000
const LIMIT_MESSAGE = `В презентации уже ${MAX_SLIDES} слайдов — это максимум`

/** Действия со слайдами с обратной связью и возможностью отмены. */
export function useSlideActions() {
  const focusField = (key = 'title') =>
    requestAnimationFrame(() => document.getElementById(`field-${key}`)?.focus({ preventScroll: false }))

  const add = useCallback((layout: SlideLayout, afterId?: string | null) => {
    if (useEditorStore.getState().addSlide(layout, afterId) === null) {
      toast.error(LIMIT_MESSAGE)
      return
    }
    focusField()
  }, [])

  const duplicate = useCallback((id: string) => {
    if (useEditorStore.getState().duplicateSlide(id)) toast.success('Слайд продублирован')
    else toast.error(LIMIT_MESSAGE)
  }, [])

  const remove = useCallback((id: string) => {
    const session = useEditorStore.getState().session
    const result = useEditorStore.getState().removeSlide(id)
    if (!result) {
      toast.error('Нельзя удалить единственный слайд')
      return
    }
    toast('Слайд удалён', {
      description: result.slide.title.trim() || undefined,
      duration: UNDO_TOAST_MS,
      action: {
        label: 'Вернуть',
        onClick: () => {
          const state = useEditorStore.getState()
          // Пользователь уже открыл другую презентацию — возвращать слайд некуда
          if (state.session === session) state.restoreSlide(result.slide, result.index)
        },
      },
    })
  }, [])

  const changeLayout = useCallback((id: string, layout: SlideLayout) => {
    const result = useEditorStore.getState().changeLayout(id, layout)
    if (!result) return
    toast(`Макет: «${getLayout(layout).label}»`, {
      description: result.trimmed
        ? 'Часть текста не поместилась в макет и обрезана. Нажмите «Отменить», чтобы вернуть.'
        : 'Текст перенесён в новый макет',
      duration: UNDO_TOAST_MS,
      action: {
        label: 'Отменить',
        onClick: () => {
          const state = useEditorStore.getState()
          const current = state.presentation?.slides.find((s) => s.id === id)
          // Слайд успели отредактировать — откат стёр бы правки
          if (current !== result.converted) {
            toast('Слайд уже изменён', { description: 'Выберите макет заново в правой панели.' })
            return
          }
          state.replaceSlide(result.previous)
        },
      },
    })
  }, [])

  const split = useCallback((id: string) => {
    const { presentation, splitSlide } = useEditorStore.getState()
    if (splitSlide(id)) toast.success('Слайд разделён на два')
    else if ((presentation?.slides.length ?? 0) >= MAX_SLIDES) toast.error(LIMIT_MESSAGE)
  }, [])

  const move = useCallback((id: string, delta: number) => {
    const { presentation, moveSlide } = useEditorStore.getState()
    const index = presentation?.slides.findIndex((s) => s.id === id) ?? -1
    if (index === -1) return
    const target = index + delta
    if (target < 0 || target >= (presentation?.slides.length ?? 0)) return
    moveSlide(index, target)
  }, [])

  return { add, duplicate, remove, changeLayout, split, move }
}
