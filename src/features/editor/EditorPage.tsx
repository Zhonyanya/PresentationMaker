import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { selectSelectedSlide, useEditorStore } from '@/store/editor-store'
import { useFlowStore } from '@/store/flow-store'
import { usePresentationScenes } from '@/hooks/usePresentationScenes'
import { EditorHeader } from './EditorHeader'
import { SlideRail } from './SlideRail'
import { SlideCanvas } from './SlideCanvas'
import { Inspector } from './Inspector'
import { ExportDialog } from './ExportDialog'
import { useSlideActions } from './useSlideActions'

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || Boolean(target.closest('[role="dialog"],[role="menu"]'))
}

export function EditorPage() {
  const presentation = useEditorStore((s) => s.presentation)
  const selected = useEditorStore(selectSelectedSlide)
  const setTitle = useEditorStore((s) => s.setTitle)
  const selectByOffset = useEditorStore((s) => s.selectByOffset)
  const backToCreate = useFlowStore((s) => s.backToCreate)
  const { move, remove } = useSlideActions()
  const [activeField, setActiveField] = useState<string | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const scenes = usePresentationScenes(presentation?.slides ?? [])

  // Клавиатура: ↑/↓ — слайды, Alt+↑/↓ — порядок, Delete — удалить, Ctrl+S — подсказка об автосохранении
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        toast('Изменения сохраняются автоматически', { description: 'Чтобы получить файл, нажмите «Скачать PPTX».' })
        return
      }
      // dnd-kit (перетаскивание с клавиатуры) и меню сами обрабатывают стрелки
      if (event.defaultPrevented || isEditableTarget(event.target) || event.ctrlKey || event.metaKey) return
      const target = event.target as HTMLElement
      const onSlideOption = Boolean(target.closest?.('[role="option"]'))
      // На кнопках и других элементах управления стрелки и Delete не перехватываем
      if (!onSlideOption && target.closest?.('button, a, [role="radio"], [role="slider"], [role="switch"]')) return
      const id = useEditorStore.getState().selectedId
      const up = event.key === 'ArrowUp' || event.key === 'PageUp' || event.key === 'ArrowLeft'
      const down = event.key === 'ArrowDown' || event.key === 'PageDown' || event.key === 'ArrowRight'
      if ((up || down) && event.altKey && id) {
        event.preventDefault()
        move(id, up ? -1 : 1)
      } else if (up || down) {
        event.preventDefault()
        selectByOffset(up ? -1 : 1)
        // Фокус следует за выбранным слайдом, если он был в списке
        requestAnimationFrame(() => {
          if (document.activeElement?.closest('[role="listbox"]')) {
            const next = useEditorStore.getState().selectedId
            document.querySelector<HTMLElement>(`[data-slide-id="${next}"]`)?.focus()
          }
        })
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && id && onSlideOption) {
        event.preventDefault()
        remove(id)
        requestAnimationFrame(() => {
          const next = useEditorStore.getState().selectedId
          document.querySelector<HTMLElement>(`[data-slide-id="${next}"]`)?.focus()
        })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [move, remove, selectByOffset])

  if (!presentation || !selected) return null
  const index = presentation.slides.findIndex((s) => s.id === selected.id)

  return (
    <div className="relative flex min-h-dvh flex-col bg-background lg:h-dvh lg:overflow-hidden">
      <EditorHeader title={presentation.title} onTitleChange={setTitle} onBack={backToCreate} onExport={() => setExportOpen(true)} />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[236px_minmax(0,1fr)_340px] lg:grid-rows-[minmax(0,1fr)] xl:grid-cols-[244px_minmax(0,1fr)_360px]">
        <div className="min-h-0 max-lg:order-2 lg:contents">
          <SlideRail slides={presentation.slides} scenes={scenes} selectedId={selected.id} />
        </div>
        <div className="flex min-h-0 min-w-0 flex-col max-lg:order-1 lg:contents">
          <SlideCanvas slide={selected} scene={scenes[index]} index={index} total={presentation.slides.length} activeField={activeField} />
        </div>
        <div className="min-h-0 max-lg:order-3 lg:contents">
          <Inspector slide={selected} index={index} total={presentation.slides.length} onFocusField={setActiveField} />
        </div>
      </div>
      <ExportDialog open={exportOpen} onOpenChange={setExportOpen} presentation={presentation} scenes={scenes} />
    </div>
  )
}
