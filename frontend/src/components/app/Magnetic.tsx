import type { PointerEvent, ReactNode } from 'react'
import { motion, useMotionValue, useReducedMotion, useSpring } from 'motion/react'

/**
 * «Магнитная» обёртка: элемент слегка тянется за курсором, пока он рядом,
 * и пружиной возвращается на место. Для главных кнопок.
 */
export function Magnetic({ children, strength = 0.3, className }: { children: ReactNode; strength?: number; className?: string }) {
  const reduceMotion = useReducedMotion()
  const x = useSpring(useMotionValue(0), { stiffness: 220, damping: 16, mass: 0.5 })
  const y = useSpring(useMotionValue(0), { stiffness: 220, damping: 16, mass: 0.5 })

  const onPointerMove = (event: PointerEvent<HTMLSpanElement>) => {
    if (reduceMotion || event.pointerType !== 'mouse') return
    const rect = event.currentTarget.getBoundingClientRect()
    x.set((event.clientX - rect.left - rect.width / 2) * strength)
    y.set((event.clientY - rect.top - rect.height / 2) * strength)
  }
  const reset = () => {
    x.set(0)
    y.set(0)
  }

  return (
    <motion.span style={{ x, y }} onPointerMove={onPointerMove} onPointerLeave={reset} className={`inline-flex ${className ?? ''}`}>
      {children}
    </motion.span>
  )
}
