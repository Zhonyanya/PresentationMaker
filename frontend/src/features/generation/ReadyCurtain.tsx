import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { plural } from '@/lib/utils'

const CURTAIN_EASE = [0.76, 0, 0.24, 1] as const
const TOTAL = 2.4

/**
 * Момент «Готово» между генерацией и редактором: чернильный занавес
 * поднимается снизу, показывает итог и уходит вверх, открывая редактор.
 */
export function ReadyCurtain({ slideCount, onDone }: { slideCount: number; onDone: () => void }) {
  // Надпись проявляется, когда занавес полностью закрыл экран, и уходит перед его подъёмом
  const [phase, setPhase] = useState<'cover' | 'show' | 'leave'>('cover')
  useEffect(() => {
    const show = window.setTimeout(() => setPhase('show'), TOTAL * 0.24 * 1000)
    const leave = window.setTimeout(() => setPhase('leave'), TOTAL * 0.56 * 1000)
    return () => {
      window.clearTimeout(show)
      window.clearTimeout(leave)
    }
  }, [])

  return (
    <motion.div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-[90] flex items-center justify-center bg-foreground text-background"
      initial={{ clipPath: 'inset(100% 0% 0% 0%)' }}
      animate={{ clipPath: ['inset(100% 0% 0% 0%)', 'inset(0% 0% 0% 0%)', 'inset(0% 0% 0% 0%)', 'inset(0% 0% 100% 0%)'] }}
      transition={{ duration: TOTAL, times: [0, 0.3, 0.62, 1], ease: [CURTAIN_EASE, 'linear', CURTAIN_EASE] }}
      onAnimationComplete={onDone}
    >
      <motion.div
        className="flex flex-col items-center px-6 text-center"
        initial={{ opacity: 0, y: 28 }}
        animate={phase === 'show' ? { opacity: 1, y: 0 } : phase === 'leave' ? { opacity: 0, y: -36 } : { opacity: 0, y: 28 }}
        transition={phase === 'leave' ? { duration: 0.45, ease: [0.76, 0, 0.24, 1] } : { duration: 0.7, ease: EASE_OUT_EXPO }}
      >
        <span className="eyebrow !text-background/55">Презентация собрана</span>
        <p className="mt-5 font-display text-[clamp(3.4rem,10vw,8rem)] leading-none font-[340] tracking-[-0.035em] italic">Готово.</p>
        <p className="mt-6 text-[15px] text-background/65">
          {slideCount} {plural(slideCount, ['слайд', 'слайда', 'слайдов'])} — проверьте текст и скачайте PPTX
        </p>
        {/* Линия под надписью прорисовывается, пока занавес стоит */}
        <motion.span
          aria-hidden
          className="mt-8 block h-px w-48 origin-left bg-background/40"
          initial={{ scaleX: 0 }}
          animate={{ scaleX: phase === 'cover' ? 0 : 1 }}
          transition={{ duration: 0.9, delay: 0.15, ease: EASE_OUT_EXPO }}
        />
      </motion.div>
    </motion.div>
  )
}
