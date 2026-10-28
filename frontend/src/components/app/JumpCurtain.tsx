import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { EASE_OUT_EXPO } from './motion'

const CURTAIN_EASE = [0.76, 0, 0.24, 1] as const

type Phase = 'idle' | 'cover' | 'reveal'

/**
 * Переход «занавесом» для дальних прыжков по странице: чернильная панель
 * поднимается снизу, под ней страница мгновенно переходит к цели,
 * затем панель уходит вверх. Так длинная сцена с прокруткой не
 * проматывается за долю секунды.
 */
const COVER_S = 0.7
const REVEAL_S = 0.85

export function useJumpCurtain() {
  const reduceMotion = useReducedMotion()
  const [phase, setPhase] = useState<Phase>('idle')
  const [label, setLabel] = useState('')
  const timers = useRef<number[]>([])

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), [])

  // Фазы ведём таймерами той же длительности, что и анимация:
  // закрыть → мгновенно перейти под занавесом → открыть
  const run = useCallback(
    (text: string, jump: () => void, after?: () => void) => {
      if (reduceMotion) {
        jump()
        after?.()
        return
      }
      timers.current.forEach((t) => window.clearTimeout(t))
      setLabel(text)
      setPhase('cover')
      const covered = COVER_S * 1000 + 60
      timers.current = [
        window.setTimeout(jump, covered),
        window.setTimeout(() => setPhase('reveal'), covered + 180),
        window.setTimeout(() => {
          setPhase('idle')
          after?.()
        }, covered + 180 + REVEAL_S * 1000 + 60),
      ]
    },
    [reduceMotion],
  )

  return { phase, label, run }
}

export function JumpCurtain({ phase, label }: Pick<ReturnType<typeof useJumpCurtain>, 'phase' | 'label'>) {
  // Свой AnimatePresence: иначе флаг initial={false} от переходов между экранами
  // в App отключает начальную анимацию, и занавес появляется рывком
  return (
    <AnimatePresence>
      {phase !== 'idle' && (
        <motion.div
          key="jump-curtain"
          aria-hidden
          className="fixed inset-0 z-[150] flex items-center justify-center bg-foreground text-background"
          initial={{ clipPath: 'inset(100% 0% 0% 0%)' }}
          animate={{ clipPath: phase === 'cover' ? 'inset(0% 0% 0% 0%)' : 'inset(0% 0% 100% 0%)' }}
          transition={{ duration: phase === 'cover' ? COVER_S : REVEAL_S, ease: CURTAIN_EASE }}
        >
          <span className="overflow-hidden pb-[0.1em]">
            <motion.span
              className="block font-display text-[clamp(2.4rem,6vw,5rem)] leading-none font-[340] tracking-[-0.03em] italic"
              initial={{ y: '110%' }}
              animate={{ y: phase === 'cover' ? '0%' : '-110%' }}
              transition={{
                duration: phase === 'cover' ? 0.8 : 0.5,
                delay: phase === 'cover' ? 0.2 : 0,
                ease: phase === 'cover' ? EASE_OUT_EXPO : CURTAIN_EASE,
              }}
            >
              {label}
            </motion.span>
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
