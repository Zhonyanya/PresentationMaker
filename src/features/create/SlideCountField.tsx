import { AnimatePresence, motion } from 'motion/react'
import { Minus, Plus } from 'lucide-react'
import { LIMITS } from '@/domain/presentation'
import { plural } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { EASE_OUT_EXPO } from '@/components/app/motion'

export function SlideCountField({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const set = (next: number) => onChange(Math.min(Math.max(next, LIMITS.slideCountMin), LIMITS.slideCountMax))
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <output aria-live="polite" className="flex items-baseline gap-3">
          <span className="relative inline-flex h-[72px] min-w-[2ch] overflow-hidden font-display text-[72px] leading-[72px] font-[360] tracking-[-0.04em] tabular-nums">
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={value}
                initial={{ y: '100%' }}
                animate={{ y: '0%' }}
                exit={{ y: '-100%' }}
                transition={{ duration: 0.55, ease: EASE_OUT_EXPO }}
              >
                {value}
              </motion.span>
            </AnimatePresence>
          </span>
          <span className="pb-2 text-[14px] text-muted-foreground">
            <span id="slide-count-label" className="sr-only">
              Количество слайдов
            </span>
            {plural(value, ['слайд', 'слайда', 'слайдов'])}
          </span>
        </output>
        <div className="flex gap-1 pb-2">
          <Button type="button" variant="outline" size="icon-sm" className="rounded-full" aria-label="Меньше слайдов" onClick={() => set(value - 1)} disabled={value <= LIMITS.slideCountMin}>
            <Minus />
          </Button>
          <Button type="button" variant="outline" size="icon-sm" className="rounded-full" aria-label="Больше слайдов" onClick={() => set(value + 1)} disabled={value >= LIMITS.slideCountMax}>
            <Plus />
          </Button>
        </div>
      </div>
      <Slider
        aria-labelledby="slide-count-label"
        min={LIMITS.slideCountMin}
        max={LIMITS.slideCountMax}
        step={1}
        value={[value]}
        onValueChange={([next]) => set(next)}
      />
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        Примерно, вместе с титульным и заключительным. Итог зависит от структуры текста.
      </p>
    </div>
  )
}
