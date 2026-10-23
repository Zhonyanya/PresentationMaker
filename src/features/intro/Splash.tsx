import { useEffect, useMemo, useState } from 'react'
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { PaperSheet } from '@/components/app/PaperSheet'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { getShowcase } from '@/features/create/showcase'
import type { SlideScene } from '@/layouts/scene'
import { useElementSize } from '@/hooks/useElementSize'

const WORD = 'Презентатор'
/** Минимальное время показа — чтобы заставка успела «раздать» листы */
const MIN_VISIBLE_MS = 2000
const SESSION_KEY = 'presentator:intro-seen'
const CURTAIN_EASE = [0.76, 0, 0.24, 1] as const

/** Показывать ли заставку: один раз за сеанс браузера, либо принудительно через ?intro */
export function shouldShowSplash(): boolean {
  try {
    if (new URLSearchParams(window.location.search).has('intro')) return true
    return window.sessionStorage.getItem(SESSION_KEY) !== '1'
  } catch {
    return true
  }
}

function markSeen() {
  try {
    window.sessionStorage.setItem(SESSION_KEY, '1')
  } catch {
    /* хранилище недоступно — заставка покажется ещё раз, не страшно */
  }
}

/** Листы падают на стол по очереди: откуда прилетают и как ложатся */
const DEAL = [
  { from: { x: -520, y: 380, rotate: -28 }, to: { x: -34, y: 22, rotate: -6.5 } },
  { from: { x: 560, y: 420, rotate: 24 }, to: { x: 40, y: 10, rotate: 5 } },
  { from: { x: -380, y: -460, rotate: 18 }, to: { x: -16, y: -6, rotate: -2.5 } },
  { from: { x: 460, y: -400, rotate: -20 }, to: { x: 22, y: -14, rotate: 2.2 } },
  { from: { x: 0, y: 560, rotate: 8 }, to: { x: 0, y: 0, rotate: -0.4 } },
]

function DealtSheet({ scene, index, width, leaving, reduceMotion }: { scene: SlideScene; index: number; width: number; leaving: boolean; reduceMotion: boolean }) {
  const height = (width * 9) / 16
  const bend = useMotionValue(reduceMotion ? 0 : 46)
  const { from, to } = DEAL[index]
  const delay = 0.3 + index * 0.2

  useEffect(() => {
    if (reduceMotion) return
    // В полёте лист выгнут, при падении на стол пружинит и распрямляется
    const controls = animate(bend, [46, 26, -10, 4, 0], { duration: 1.2, delay, times: [0, 0.4, 0.66, 0.86, 1], ease: 'easeInOut' })
    return () => controls.stop()
  }, [bend, delay, reduceMotion])

  return (
    <motion.div
      className="absolute top-1/2 left-1/2"
      style={{
        width,
        height,
        marginLeft: -width / 2,
        marginTop: -height / 2,
        zIndex: index,
        perspective: 1100,
        isolation: 'isolate',
        filter: 'drop-shadow(0 1px 1px rgb(20 20 20 / 0.08)) drop-shadow(0 22px 26px rgb(20 20 20 / 0.18))',
      }}
      initial={reduceMotion ? { ...to, opacity: 0 } : { ...from, opacity: 0, scale: 1.08 }}
      animate={
        leaving && !reduceMotion
          ? { x: to.x * 1.6, y: to.y - 140 - index * 26, rotate: to.rotate * 1.8, opacity: 0, scale: 0.96 }
          : { ...to, opacity: 1, scale: 1 }
      }
      transition={
        leaving
          ? { duration: 0.75, delay: (DEAL.length - 1 - index) * 0.04, ease: CURTAIN_EASE }
          : { duration: 1.15, delay: reduceMotion ? 0 : delay, ease: EASE_OUT_EXPO }
      }
    >
      <PaperSheet width={width} height={height} bend={bend}>
        {() => <SlideRenderer scene={scene} scale={width / SLIDE_PX.width} />}
      </PaperSheet>
    </motion.div>
  )
}

/** Тонкая линия рамки, которая прорисовывается */
function Rule({ className, delay }: { className: string; delay: number }) {
  return (
    <motion.span
      aria-hidden
      className={`absolute bg-foreground/20 ${className}`}
      style={{ originX: 0 }}
      initial={{ scaleX: 0 }}
      animate={{ scaleX: 1 }}
      transition={{ duration: 1.4, delay, ease: EASE_OUT_EXPO }}
    />
  )
}

interface SplashProps {
  /** Занавес начал подниматься — пора показывать сайт под ним */
  onReveal: () => void
  /** Заставка полностью ушла */
  onDone: () => void
}

/**
 * Заставка при первом открытии сайта. На стол «раздаются» настоящие слайды
 * демо-презентации, крупный счётчик показывает готовность (загрузку шрифтов),
 * затем стопка уходит вверх и двойной занавес открывает сайт.
 */
export function Splash({ onReveal, onDone }: SplashProps) {
  const reduceMotion = Boolean(useReducedMotion())
  const [ready, setReady] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [stageRef, stage] = useElementSize<HTMLDivElement>()
  const scenes = useMemo(() => {
    const { gallery } = getShowcase()
    return [gallery[3], gallery[2], gallery[1], gallery[4] ?? gallery[2], gallery[0]].filter(Boolean)
  }, [])

  // Счётчик 000 → 100: быстро до 72, остаток — когда всё готово
  const progress = useMotionValue(0)
  const counter = useTransform(progress, (v) => String(Math.round(v)).padStart(3, '0'))

  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    let cancelled = false
    const run = animate(progress, 72, { duration: reduceMotion ? 0.2 : 1.8, ease: [0.3, 0.1, 0.3, 1] })
    const minDelay = new Promise((resolve) => window.setTimeout(resolve, reduceMotion ? 300 : MIN_VISIBLE_MS))
    const fonts = 'fonts' in document ? document.fonts.ready : Promise.resolve()
    void Promise.all([minDelay, fonts]).then(() => {
      if (cancelled) return
      run.stop()
      void animate(progress, 100, { duration: 0.5, ease: EASE_OUT_EXPO }).then(() => {
        if (!cancelled) setReady(true)
      })
    })
    return () => {
      cancelled = true
      run.stop()
      document.body.style.overflow = previous
    }
  }, [progress, reduceMotion])

  // 100 → короткая пауза → стопка уходит → занавес
  useEffect(() => {
    if (!ready) return
    const leave = window.setTimeout(() => setLeaving(true), reduceMotion ? 0 : 250)
    const reveal = window.setTimeout(
      () => {
        markSeen()
        onReveal()
      },
      reduceMotion ? 0 : 600,
    )
    return () => {
      window.clearTimeout(leave)
      window.clearTimeout(reveal)
    }
  }, [ready, reduceMotion, onReveal])

  const curtainUp = leaving ? 'inset(0% 0% 100% 0%)' : 'inset(0% 0% 0% 0%)'
  const sheetWidth = Math.min(stage.width * 0.62, 620)

  return (
    <div className="fixed inset-0 z-[100]" role="status" aria-label="Загрузка" aria-busy={!leaving}>
      {/* Нижний слой занавеса — чернильный, поднимается чуть позже бумажного */}
      <motion.div
        className="absolute inset-0 bg-foreground"
        initial={false}
        animate={{ clipPath: curtainUp }}
        transition={{ duration: reduceMotion ? 0.2 : 1, ease: CURTAIN_EASE, delay: leaving && !reduceMotion ? 0.5 : 0 }}
        onAnimationComplete={() => {
          if (leaving) onDone()
        }}
      />

      <motion.div
        className="absolute inset-0 overflow-hidden bg-background"
        initial={false}
        animate={{ clipPath: curtainUp }}
        transition={{ duration: reduceMotion ? 0.2 : 1, ease: CURTAIN_EASE, delay: leaving && !reduceMotion ? 0.35 : 0 }}
      >
        <div className="absolute inset-0 px-5 py-6 sm:px-10 sm:py-8">
          <div className="relative size-full">
            {/* Рамка из волосяных линий */}
            <Rule className="top-10 right-0 left-0 h-px" delay={0.1} />
            <Rule className="right-0 bottom-[7.5rem] left-0 h-px sm:bottom-[9.5rem]" delay={0.25} />

            {/* Рубрики, как на обложке */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: leaving ? 0 : 1 }}
              transition={{ duration: 0.8, delay: leaving ? 0 : 0.3 }}
              className="absolute top-0 right-0 left-0 flex items-center justify-between"
            >
              <span className="flex items-center gap-3">
                <span className="inline-flex size-7 items-center justify-center bg-foreground font-display text-[16px] leading-none text-background italic" aria-hidden>
                  П
                </span>
                <span className="eyebrow">Ассистент для выступлений</span>
              </span>
              <span className="eyebrow hidden sm:inline">Прототип · {new Date().getFullYear()}</span>
            </motion.div>

            {/* Стол со стопкой слайдов */}
            <div ref={stageRef} className="absolute top-16 right-0 bottom-[9rem] left-0 sm:bottom-[11rem]" aria-hidden>
              {stage.width > 0 &&
                scenes.map((scene, i) => <DealtSheet key={i} scene={scene} index={i} width={sheetWidth} leaving={leaving} reduceMotion={reduceMotion} />)}
            </div>

            {/* Низ обложки: счётчик и название */}
            <div className="absolute right-0 bottom-0 left-0 flex items-end justify-between gap-6">
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={leaving ? { opacity: 0, y: -20 } : { opacity: 1, y: 0 }}
                transition={{ duration: 0.9, ease: EASE_OUT_EXPO }}
                className="flex items-end gap-3"
              >
                <motion.span className="font-display text-[clamp(4.5rem,13vw,10rem)] leading-[0.8] font-[340] tracking-[-0.04em] tabular-nums italic">
                  {counter}
                </motion.span>
                <span className="eyebrow mb-2">%</span>
              </motion.div>

              <motion.div
                initial={{ opacity: 1 }}
                animate={leaving ? { opacity: 0, y: -20 } : { opacity: 1, y: 0 }}
                transition={{ duration: 0.7, ease: CURTAIN_EASE }}
                className="flex flex-col items-end pb-1 text-right"
              >
                <h1 className="flex overflow-hidden pb-[0.1em] font-display text-[clamp(1.9rem,4.2vw,3.4rem)] leading-none font-[380] tracking-[-0.03em]" aria-label={WORD}>
                  {WORD.split('').map((letter, i) => (
                    <motion.span
                      key={i}
                      aria-hidden
                      className="inline-block"
                      initial={reduceMotion ? false : { y: '110%' }}
                      animate={{ y: '0%' }}
                      transition={{ duration: 1, delay: 0.5 + i * 0.04, ease: EASE_OUT_EXPO }}
                    >
                      {letter}
                    </motion.span>
                  ))}
                </h1>
                <motion.span
                  className="mt-3 font-display text-[15px] text-muted-foreground italic"
                  initial={reduceMotion ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.9, delay: 1.1, ease: EASE_OUT_EXPO }}
                >
                  Из доклада — в презентацию
                </motion.span>
              </motion.div>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
