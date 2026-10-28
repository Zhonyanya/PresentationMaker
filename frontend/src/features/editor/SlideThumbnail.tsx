import { memo, useEffect, useRef } from 'react'
import { motion } from 'motion/react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { ArrowDown, ArrowUp, Copy, MoreHorizontal, Plus, Trash2, TriangleAlert } from 'lucide-react'
import type { Slide } from '@/domain/presentation'
import type { SlideScene } from '@/layouts/scene'
import { getLayout } from '@/layouts/registry'
import { cn } from '@/lib/utils'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { useSlideActions } from './useSlideActions'
import { AddSlideMenu } from './AddSlideMenu'
import { EASE_OUT_EXPO } from '@/components/app/motion'

interface SlideThumbnailProps {
  slide: Slide
  scene: SlideScene
  index: number
  total: number
  selected: boolean
  overflow: boolean
  width: number
  onSelect: (id: string) => void
}

export const SlideThumbnail = memo(function SlideThumbnail({ slide, scene, index, total, selected, overflow, width, onSelect }: SlideThumbnailProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: slide.id })
  const { duplicate, remove, move } = useSlideActions()
  const itemRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (selected) itemRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [selected])

  const title = slide.title.trim() || 'Без заголовка'
  const label = `Слайд ${index + 1}: ${title}. Макет «${getLayout(slide.layout).label}»${overflow ? '. Слишком много текста' : ''}`

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn('group relative flex shrink-0 gap-2', isDragging && 'z-10')}
    >
      <span
        className={cn('w-5 pt-0.5 text-right font-display text-[13px] italic tabular-nums transition-colors duration-500', selected ? 'text-foreground' : 'text-foreground/35')}
        aria-hidden
      >
        {index + 1}
      </span>
      <div
        ref={itemRef}
        {...attributes}
        {...listeners}
        role="option"
        aria-roledescription="слайд, можно перетащить"
        aria-selected={selected}
        aria-label={label}
        tabIndex={selected ? 0 : -1}
        data-slide-id={slide.id}
        onClick={() => onSelect(slide.id)}
        onKeyDown={(e) => {
          listeners?.onKeyDown?.(e)
          if (e.key === 'Enter') onSelect(slide.id)
        }}
        className={cn(
          'relative cursor-pointer overflow-hidden bg-white outline-none transition-[box-shadow,transform] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]',
          selected
            ? 'shadow-slide ring-[1.5px] ring-foreground ring-offset-2 ring-offset-background'
            : 'ring-1 ring-foreground/10 hover:-translate-y-0.5 hover:shadow-slide',
          'focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          isDragging && 'scale-[1.03] shadow-md',
        )}
      >
        <motion.div
          initial={{ opacity: 0, y: 10, scale: 0.96 }}
          exit={{ opacity: 0, scale: 0.9, rotate: -3, transition: { duration: 0.3, ease: 'easeIn' } }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, delay: Math.min(index, 12) * 0.04, ease: EASE_OUT_EXPO }}
        >
          <SlideRenderer scene={scene} scale={width / SLIDE_PX.width} />
        </motion.div>
        {overflow && (
          <span className="absolute bottom-1 left-1 inline-flex items-center gap-0.5 rounded bg-white/95 px-1 py-0.5 text-[10px] font-medium text-destructive shadow-xs">
            <TriangleAlert className="size-2.5" aria-hidden />
            Текст
          </span>
        )}
      </div>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label={`Действия со слайдом ${index + 1}`}
            onPointerDown={(e) => e.stopPropagation()}
            className={cn(
              'absolute top-1 right-1 inline-flex size-6 items-center justify-center rounded-full bg-background text-muted-foreground shadow-sm ring-1 ring-foreground/15 transition-opacity outline-none hover:text-foreground focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:opacity-100',
              'opacity-0 group-hover:opacity-100 max-lg:opacity-100',
            )}
          >
            <MoreHorizontal className="size-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="right" className="w-56">
          <DropdownMenuItem onSelect={() => duplicate(slide.id)}>
            <Copy />
            Дублировать
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => move(slide.id, -1)} disabled={index === 0}>
            <ArrowUp />
            Переместить выше
            <DropdownMenuShortcut>Alt+↑</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => move(slide.id, 1)} disabled={index === total - 1}>
            <ArrowDown />
            Переместить ниже
            <DropdownMenuShortcut>Alt+↓</DropdownMenuShortcut>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={() => remove(slide.id)} disabled={total <= 1}>
            <Trash2 />
            Удалить
            <DropdownMenuShortcut>Del</DropdownMenuShortcut>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {selected && (
        <AddSlideMenu afterId={slide.id}>
          <button
            type="button"
            aria-label="Добавить слайд после этого"
            onPointerDown={(e) => e.stopPropagation()}
            className="absolute -bottom-2.5 left-[calc(50%+14px)] z-10 inline-flex size-5 -translate-x-1/2 items-center justify-center rounded-full bg-foreground text-background opacity-0 shadow-sm transition-opacity outline-none group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:opacity-100 max-lg:hidden"
          >
            <Plus className="size-3" strokeWidth={2.5} />
          </button>
        </AddSlideMenu>
      )}
    </div>
  )
})
