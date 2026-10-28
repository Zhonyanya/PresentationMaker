import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronDown, ChevronUp, Scissors, TriangleAlert } from 'lucide-react'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import type { Slide } from '@/domain/presentation'
import type { SlideScene } from '@/layouts/scene'
import { getLayout } from '@/layouts/registry'
import { canSplitSlide } from '@/domain/operations'
import { useElementSize } from '@/hooks/useElementSize'
import { sceneHasOverflow } from '@/hooks/usePresentationScenes'
import { Button } from '@/components/ui/button'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { useEditorStore } from '@/store/editor-store'
import { useSlideActions } from './useSlideActions'

interface SlideCanvasProps {
  slide: Slide
  scene: SlideScene
  index: number
  total: number
  activeField: string | null
  readOnly?: boolean
}

const PADDING = 40

export function SlideCanvas({ slide, scene, index, total, activeField, readOnly }: SlideCanvasProps) {
  const [ref, size] = useElementSize<HTMLDivElement>()
  const selectByOffset = useEditorStore((s) => s.selectByOffset)
  const { split } = useSlideActions()
  const overflow = sceneHasOverflow(scene)
  const padding = size.width < 640 ? 16 : PADDING
  const scale = Math.max(0.1, Math.min((size.width - padding * 2) / SLIDE_PX.width, (size.height - padding * 2) / SLIDE_PX.height))

  const focusField = (field: string) => document.getElementById(`field-${field}`)?.focus()

  // Направление перелистывания: следующий слайд приезжает снизу, предыдущий — сверху
  // (паттерн «предыдущее значение в состоянии» — корректен и в StrictMode)
  const [nav, setNav] = useState({ index, direction: 1 })
  if (nav.index !== index) setNav({ index, direction: index > nav.index ? 1 : -1 })
  const direction = nav.index !== index ? (index > nav.index ? 1 : -1) : nav.direction

  return (
    <section aria-label="Предварительный просмотр слайда" className="flex min-h-0 min-w-0 flex-col bg-canvas">
      <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-5">
        <div className="flex min-w-0 items-center gap-3">
          <p className="font-display text-[17px] italic tabular-nums">
            <span className="sr-only">Слайд </span>
            {String(index + 1).padStart(2, '0')}
            <span className="text-muted-foreground/60"> / {String(total).padStart(2, '0')}</span>
          </p>
          <span className="relative hidden h-px w-28 bg-border sm:block" aria-hidden>
            <motion.span
              className="absolute inset-y-0 left-0 bg-foreground"
              animate={{ width: `${((index + 1) / total) * 100}%` }}
              transition={{ duration: 0.5, ease: EASE_OUT_EXPO }}
            />
          </span>
          <span className="eyebrow truncate">{getLayout(slide.layout).label}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <SimpleTooltip label="Предыдущий слайд" shortcut="↑">
            <Button variant="ghost" size="icon-sm" aria-label="Предыдущий слайд" onClick={() => selectByOffset(-1)} disabled={index === 0}>
              <ChevronUp />
            </Button>
          </SimpleTooltip>
          <SimpleTooltip label="Следующий слайд" shortcut="↓">
            <Button variant="ghost" size="icon-sm" aria-label="Следующий слайд" onClick={() => selectByOffset(1)} disabled={index === total - 1}>
              <ChevronDown />
            </Button>
          </SimpleTooltip>
        </div>
      </div>

      <div ref={ref} className="relative min-h-0 flex-1 max-lg:aspect-video max-lg:flex-none">
        {size.width > 0 && (
          <div className="absolute inset-0 flex items-center justify-center overflow-hidden">
            <AnimatePresence mode="popLayout" initial={false} custom={direction}>
              <motion.div
                key={slide.id}
                custom={direction}
                variants={{
                  enter: (d: number) => ({ opacity: 0, y: d * 28 }),
                  center: { opacity: 1, y: 0 },
                  exit: (d: number) => ({ opacity: 0, y: d * -28 }),
                }}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.6, ease: EASE_OUT_EXPO }}
                className="shadow-slide ring-1 ring-foreground/5"
              >
                <SlideRenderer scene={scene} scale={scale} showPlaceholders activeField={activeField} onFieldClick={readOnly ? undefined : focusField} />
              </motion.div>
            </AnimatePresence>
          </div>
        )}
      </div>

      {overflow && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
          className="mx-5 mb-5 flex flex-col gap-3 border-l-2 border-destructive bg-background px-4 py-3 text-[13px] sm:flex-row sm:items-center sm:justify-between"
          role="status"
        >
          <p className="flex items-start gap-2 text-destructive">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Слишком много текста: шрифт уменьшен ниже рекомендуемого и будет плохо читаться на экране. Сократите текст или разделите
              слайд.
            </span>
          </p>
          {!readOnly && canSplitSlide(slide) && (
            <Button variant="outline" size="sm" className="shrink-0" onClick={() => split(slide.id)}>
              <Scissors />
              Разделить слайд
            </Button>
          )}
        </motion.div>
      )}
    </section>
  )
}
