import { useCallback } from 'react'
import { AnimatePresence } from 'motion/react'
import { DndContext, KeyboardSensor, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy, sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { restrictToParent } from './dnd-modifiers'
import { Plus } from 'lucide-react'
import type { Slide } from '@/domain/presentation'
import type { SlideScene } from '@/layouts/scene'
import { sceneHasOverflow } from '@/hooks/usePresentationScenes'
import { plural } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useEditorStore } from '@/store/editor-store'
import { SlideThumbnail } from './SlideThumbnail'
import { AddSlideMenu } from './AddSlideMenu'

const THUMB_WIDTH = 176

interface SlideRailProps {
  slides: Slide[]
  scenes: SlideScene[]
  selectedId: string | null
}

export function SlideRail({ slides, scenes, selectedId }: SlideRailProps) {
  const select = useEditorStore((s) => s.select)
  const moveSlide = useEditorStore((s) => s.moveSlide)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
      keyboardCodes: { start: ['Space'], cancel: ['Escape'], end: ['Space', 'Enter'] },
    }),
  )

  const onDragEnd = useCallback(
    ({ active, over }: DragEndEvent) => {
      if (!over || active.id === over.id) return
      const from = slides.findIndex((s) => s.id === active.id)
      const to = slides.findIndex((s) => s.id === over.id)
      moveSlide(from, to)
    },
    [slides, moveSlide],
  )

  return (
    <nav aria-label="Слайды" className="flex min-h-0 flex-col border-border bg-background max-lg:border-y lg:border-r">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-3 lg:px-4">
        <h2 className="eyebrow !text-foreground">
          {slides.length} {plural(slides.length, ['слайд', 'слайда', 'слайдов'])}
        </h2>
        <AddSlideMenu afterId={selectedId}>
          <Button variant="ghost" size="sm" className="-mr-2 h-7 text-[12.5px]">
            <Plus />
            Добавить
          </Button>
        </AddSlideMenu>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd} modifiers={[restrictToParent]}>
        <SortableContext items={slides.map((s) => s.id)} strategy={rectSortingStrategy}>
          <div
            role="listbox"
            aria-label="Порядок слайдов. Пробел — взять и перенести слайд, стрелки — выбрать"
            aria-orientation="vertical"
            className="scroll-thin relative flex min-h-0 flex-1 gap-4 overflow-auto p-3 max-lg:flex-row lg:flex-col lg:px-3 lg:py-4"
          >
            {/* AnimatePresence — чтобы удалённая миниатюра плавно исчезала */}
            <AnimatePresence initial={false}>
            {slides.map((slide, index) => (
              <SlideThumbnail
                key={slide.id}
                slide={slide}
                scene={scenes[index]}
                index={index}
                total={slides.length}
                selected={slide.id === selectedId}
                overflow={sceneHasOverflow(scenes[index])}
                width={THUMB_WIDTH}
                onSelect={select}
              />
            ))}
            </AnimatePresence>
          </div>
        </SortableContext>
      </DndContext>
    </nav>
  )
}
