import { useEffect } from 'react'
import Lenis from 'lenis'
import 'lenis/dist/lenis.css'

/**
 * Плавная инерционная прокрутка страницы (Lenis).
 * Включается только на длинных страницах (главная) и не включается при
 * системной настройке «Уменьшить движение». Прокрутка остаётся нативной —
 * motion/useScroll и position: sticky работают как обычно.
 */
let instance: Lenis | null = null

export function useSmoothScroll(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return
    const lenis = new Lenis({ duration: 1.15, easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), smoothWheel: true })
    instance = lenis
    let frame = requestAnimationFrame(function loop(time) {
      lenis.raf(time)
      frame = requestAnimationFrame(loop)
    })
    return () => {
      cancelAnimationFrame(frame)
      lenis.destroy()
      instance = null
    }
  }, [enabled])
}

/** Мгновенно перейти к элементу — без анимации прокрутки (под занавесом). */
export function jumpTo(element: HTMLElement | null, offset = -80) {
  if (!element) return
  if (instance) instance.scrollTo(element, { offset, immediate: true, force: true })
  else window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY + offset, behavior: 'instant' })
}

/** Плавно прокрутить к элементу — через Lenis, если он включён, иначе нативно. */
export function smoothScrollTo(element: HTMLElement | null, offset = -80) {
  if (!element) return
  if (instance) instance.scrollTo(element, { offset, duration: 1.4 })
  else element.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
