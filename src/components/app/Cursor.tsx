import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring } from 'motion/react'
import { ArrowRight } from 'lucide-react'

/**
 * Фирменный курсор главной страницы.
 *
 * Чернильная стрелка с бумажным контуром — видна и на бумаге, и на тёмной
 * сцене, и на синих слайдах. Следует за мышью без задержки; при быстром
 * движении чуть наклоняется по ходу, при клике «нажимается». Над кнопками
 * у кончика появляется терракотовый ромб — знак из фирменной графики, над
 * элементами с data-cursor="…" — плашка с подписью. В полях ввода остаётся
 * обычный текстовый курсор. Только для мыши/тачпада.
 */
export function SiteCursor() {
  const reduceMotion = useReducedMotion()
  const [enabled] = useState(() => typeof window !== 'undefined' && window.matchMedia('(pointer: fine)').matches)
  const active = enabled && !reduceMotion

  const [state, setState] = useState({ visible: false, interactive: false, text: false, label: null as string | null })
  const [pressed, setPressed] = useState(false)
  const x = useMotionValue(-100)
  const y = useMotionValue(-100)
  // Наклон по горизонтальной скорости — пружиной, чтобы движение было мягким
  const tiltTarget = useMotionValue(0)
  const tilt = useSpring(tiltTarget, { stiffness: 260, damping: 18 })
  const last = useRef({ x: 0, t: 0 })

  useEffect(() => {
    if (!active) return
    document.documentElement.classList.add('site-cursor')

    const onMove = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return
      x.set(event.clientX)
      y.set(event.clientY)
      const now = performance.now()
      const dt = Math.max(8, now - last.current.t)
      const velocity = (event.clientX - last.current.x) / dt
      last.current = { x: event.clientX, t: now }
      tiltTarget.set(Math.max(-14, Math.min(14, velocity * 9)))

      const target = event.target instanceof Element ? event.target : null
      const next = {
        visible: true,
        text: Boolean(target?.closest('input, textarea, select, [contenteditable="true"]')),
        interactive: Boolean(target?.closest('a, button, [role="button"], [role="option"], [role="radio"], label, summary, [data-cursor]')),
        label: target?.closest<HTMLElement>('[data-cursor]')?.dataset.cursor ?? null,
      }
      setState((s) => (s.visible === next.visible && s.text === next.text && s.interactive === next.interactive && s.label === next.label ? s : next))
    }
    // Стрелка возвращается в ровное положение, когда мышь замирает
    const settle = window.setInterval(() => {
      if (performance.now() - last.current.t > 90) tiltTarget.set(0)
    }, 90)
    const onLeave = () => setState((s) => ({ ...s, visible: false }))
    const onDown = () => setPressed(true)
    const onUp = () => setPressed(false)

    window.addEventListener('pointermove', onMove, { passive: true })
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('pointerup', onUp)
    document.addEventListener('pointerleave', onLeave)
    return () => {
      document.documentElement.classList.remove('site-cursor')
      window.clearInterval(settle)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('pointerup', onUp)
      document.removeEventListener('pointerleave', onLeave)
    }
  }, [active, x, y, tiltTarget])

  if (!active) return null
  const hidden = !state.visible || state.text

  return (
    <motion.div aria-hidden className="pointer-events-none fixed top-0 left-0 z-[200]" style={{ x, y }}>
      <motion.div animate={{ opacity: hidden ? 0 : 1 }} transition={{ duration: 0.15 }}>
        {/* Кончик стрелки — точно в точке курсора */}
        <motion.svg
          width="22"
          height="26"
          viewBox="0 0 22 26"
          className="absolute -top-[2px] -left-[2px] overflow-visible drop-shadow-[0_2px_3px_rgb(20_20_20/0.28)]"
          style={{ rotate: tilt, originX: '2px', originY: '2px' }}
          animate={{ scale: pressed ? 0.82 : state.interactive ? 0.92 : 1 }}
          transition={{ type: 'spring', stiffness: 520, damping: 26 }}
        >
          <path
            d="M2 2 L2 20.5 L6.8 16 L10.1 23.2 L13.2 21.8 L10 14.8 L16.6 14.8 Z"
            fill="#141414"
            stroke="#f3f0e8"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </motion.svg>

        {/* Терракотовый ромб у кончика — над кнопками и ссылками */}
        <motion.span
          className="absolute top-[17px] left-[17px] size-[7px] bg-brand ring-1 ring-[#f3f0e8]"
          initial={false}
          animate={{ scale: state.interactive && !state.label ? 1 : 0, rotate: state.interactive ? 45 : 0 }}
          transition={{ type: 'spring', stiffness: 480, damping: 22 }}
        />

        {/* Плашка-подсказка, прикреплённая к стрелке */}
        <AnimatePresence>
          {state.label && (
            <motion.span
              key={state.label}
              initial={{ opacity: 0, x: 14, y: 30, scale: 0.9 }}
              animate={{ opacity: 1, x: 20, y: 30, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9, transition: { duration: 0.15 } }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
              className="absolute top-0 left-0 flex items-center gap-2 bg-foreground px-3 py-1.5 text-[11px] font-medium tracking-[0.14em] whitespace-nowrap text-background uppercase shadow-[0_8px_20px_-8px_rgb(20_20_20/0.5)] ring-1 ring-background/40"
            >
              {state.label}
              <ArrowRight className="size-3" />
            </motion.span>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.div>
  )
}
