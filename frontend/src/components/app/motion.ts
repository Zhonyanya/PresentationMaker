import type { Transition, Variants } from 'motion/react'

/** Общие параметры анимаций интерфейса — чтобы движение было единым по всему приложению. */
export const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const

export const spring: Transition = { type: 'spring', stiffness: 380, damping: 32, mass: 0.8 }
export const softSpring: Transition = { type: 'spring', stiffness: 160, damping: 22 }

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.9, ease: EASE_OUT_EXPO } },
}

/** Строка заголовка выезжает из-под маски — классический редакционный приём */
export const lineReveal: Variants = {
  hidden: { y: '105%' },
  show: { y: '0%', transition: { duration: 1.1, ease: EASE_OUT_EXPO } },
}

export const stagger = (delayChildren = 0.05, staggerChildren = 0.07): Variants => ({
  hidden: {},
  show: { transition: { delayChildren, staggerChildren } },
})

/**
 * Переход между экранами приложения. Без filter: он, как и transform, ломает
 * position: fixed/sticky у потомков (липкие шапки), а transform в покое снимается.
 */
export const pageTransition: Variants = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE_OUT_EXPO } },
  exit: { opacity: 0, y: -10, transition: { duration: 0.22, ease: 'easeIn' } },
}
