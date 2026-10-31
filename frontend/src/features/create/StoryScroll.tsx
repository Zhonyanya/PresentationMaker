import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useInView, useReducedMotion, useScroll, useTransform, type MotionValue } from 'motion/react'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { useElementSize } from '@/hooks/useElementSize'
import { demoExamples } from '@/data/demo-examples'
import { plural } from '@/lib/utils'
import type { SlideScene } from '@/layouts/scene'
import { getShowcase } from './showcase'

/**
 * Кинематографичная секция «Как это работает», управляемая прокруткой.
 * Экран закреплён, а прокрутка двигает сцену:
 *  01 — лист доклада, заголовки разделов подсвечиваются;
 *  02 — заголовки вылетают из листа, фон темнеет, появляется 3D-карусель
 *       настоящих слайдов и вращается вместе с прокруткой;
 *  03 — карусель складывается в стопку, появляется готовый файл .pptx.
 */

const PAPER = '#f3f0e8'
const INK = '#141414'

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const ease = (t: number) => 1 - Math.pow(1 - t, 3)
/** Прогресс внутри отрезка [from, to] прокрутки, 0…1 */
const segment = (p: number, from: number, to: number) => clamp01((p - from) / (to - from))

interface DocLine {
  text: string
  heading: boolean
}

function useDocument(): DocLine[] {
  return useMemo(() => {
    const lines = demoExamples[0].text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .slice(2, 22)
    return lines.map((text) => ({
      text: text.replace(/^-\s*/, '— '),
      heading: text.length < 40 && !/[.;:,]$/.test(text) && !text.startsWith('-') && !/^\d/.test(text),
    }))
  }, [])
}

function DocumentSheet({ progress, lines }: { progress: MotionValue<number>; lines: DocLine[] }) {
  const x = useTransform(progress, (p) => `${lerp(0, -34, ease(segment(p, 0.3, 0.48)))}vw`)
  const y = useTransform(progress, (p) => lerp(80, 0, ease(segment(p, 0, 0.1))) + lerp(0, 60, ease(segment(p, 0.3, 0.48))))
  const scale = useTransform(progress, (p) => lerp(1, 0.6, ease(segment(p, 0.3, 0.48))))
  const rotate = useTransform(progress, (p) => lerp(-3, 0, ease(segment(p, 0, 0.1))) + lerp(0, -8, ease(segment(p, 0.3, 0.48))))
  const opacity = useTransform(progress, (p) => segment(p, 0, 0.06) * (1 - segment(p, 0.44, 0.52)))

  let headingIndex = -1
  return (
    <motion.div
      style={{ x, y, scale, rotate, opacity }}
      className="absolute top-1/2 left-1/2 -mt-[min(36vh,300px)] -ml-[min(22vw,210px)] h-[min(72vh,600px)] w-[min(44vw,420px)] overflow-hidden bg-[#fbfaf6] p-[min(3vw,34px)] shadow-[0_2px_4px_rgb(20_20_20/0.06),0_40px_80px_-30px_rgb(20_20_20/0.45)]"
    >
      <p className="eyebrow mb-3">Доклад · {lines.length * 12} слов</p>
      <p className="mb-5 font-display text-[clamp(1.2rem,2vw,1.6rem)] leading-tight">Итоги учебного года</p>
      <div className="flex flex-col gap-[0.42rem] text-[clamp(9px,0.85vw,11.5px)] leading-[1.55] text-foreground/75">
        {lines.map((line, i) => {
          if (!line.heading) return <p key={i}>{line.text}</p>
          headingIndex += 1
          const order = headingIndex
          return <Highlighted key={i} progress={progress} order={order} text={line.text} />
        })}
      </div>
    </motion.div>
  )
}

/** Заголовок раздела в докладе: по прокрутке под ним прорисовывается терракотовая линия */
function Highlighted({ progress, order, text }: { progress: MotionValue<number>; order: number; text: string }) {
  const scaleX = useTransform(progress, (p) => segment(p, 0.1 + order * 0.04, 0.16 + order * 0.04))
  return (
    <p className="relative mt-1 w-fit text-[1.15em] font-semibold text-foreground">
      {text}
      <motion.span style={{ scaleX }} className="absolute -bottom-0.5 left-0 h-[2px] w-full origin-left bg-brand" />
    </p>
  )
}

/** Заголовки разделов вылетают из листа и превращаются в слайды */
function Fragment({ progress, index, text }: { progress: MotionValue<number>; index: number; text: string }) {
  const t = (p: number) => ease(segment(p, 0.3 + index * 0.02, 0.5 + index * 0.02))
  const x = useTransform(progress, (p) => `${lerp(-30 + index * 1.5, -24 + index * 12, t(p))}vw`)
  const y = useTransform(progress, (p) => lerp(-120 + index * 52, -30 + (index % 2) * 60, t(p)))
  const rotate = useTransform(progress, (p) => lerp(0, (index % 2 ? 1 : -1) * 6, t(p)))
  const opacity = useTransform(progress, (p) => segment(p, 0.3 + index * 0.02, 0.34 + index * 0.02) * (1 - segment(p, 0.5, 0.56)))
  return (
    <motion.span
      style={{ x, y, rotate, opacity }}
      className="absolute top-1/2 left-1/2 font-display text-[clamp(1.1rem,2.2vw,1.9rem)] whitespace-nowrap italic"
    >
      {text}
    </motion.span>
  )
}

function RingCard({ progress, scene, index, count, radius, width }: { progress: MotionValue<number>; scene: SlideScene; index: number; count: number; radius: number; width: number }) {
  const height = (width * 9) / 16
  const angle = (360 / count) * index
  // Сборка в стопку в финале
  const collapse = (p: number) => ease(segment(p, 0.84, 0.94))
  const transform = useTransform(progress, (p) => {
    const c = collapse(p)
    // В стопке листы параллельны (без поворота вокруг общей оси — иначе плоскости
    // пересекаются), лежат друг над другом и чуть развёрнуты в своей плоскости
    const a = lerp(angle, Math.round(angle / 360) * 360, c)
    const r = lerp(radius, index * 2, c)
    const y = lerp(0, -index * 7, c)
    const tilt = lerp(0, (index - (count - 1) / 2) * 1.6, c)
    const appear = ease(segment(p, 0.44 + index * 0.025, 0.56 + index * 0.025))
    const s = lerp(0.55, 1, appear)
    return `rotateY(${a}deg) translateZ(${r}px) translateY(${y}px) rotateZ(${tilt}deg) scale(${s})`
  })
  const opacity = useTransform(progress, (p) => ease(segment(p, 0.44 + index * 0.025, 0.54 + index * 0.025)))
  return (
    <motion.div
      style={{ transform, opacity, width, height, marginLeft: -width / 2, marginTop: -height / 2, transformStyle: 'preserve-3d' }}
      className="absolute top-1/2 left-1/2"
    >
      {/* Лицевая сторона — настоящий слайд */}
      <div
        className="absolute inset-0 overflow-hidden bg-white shadow-[0_24px_48px_-22px_rgb(0_0_0/0.4)]"
        style={{ backfaceVisibility: 'hidden', WebkitBackfaceVisibility: 'hidden' }}
      >
        <SlideRenderer scene={scene} scale={width / SLIDE_PX.width} />
      </div>
      {/* Оборот листа — бумага с монограммой, а не зеркальный текст */}
      <div
        className="absolute inset-0 flex items-center justify-center bg-[#e7e1d4]"
        style={{ transform: 'rotateY(180deg)', backfaceVisibility: 'hidden', WebkitBackfaceVisibility: 'hidden' }}
      >
        <span className="font-display text-[clamp(1.6rem,3vw,2.6rem)] text-[#141414]/25 italic">П</span>
      </div>
    </motion.div>
  )
}

function Chapter({ progress, from, to, number, title, text, color }: { progress: MotionValue<number>; from: number; to: number; number: string; title: string; text: string; color: MotionValue<string> }) {
  const opacity = useTransform(progress, (p) => segment(p, from, from + 0.05) * (1 - segment(p, to - 0.05, to)))
  const y = useTransform(progress, (p) => lerp(30, 0, ease(segment(p, from, from + 0.07))) - lerp(0, 30, segment(p, to - 0.05, to)))
  return (
    <motion.div style={{ opacity, y, color }} className="absolute top-0 left-0 max-w-[30ch]">
      <span className="font-display text-[clamp(3.5rem,7vw,6.5rem)] leading-none font-[340] italic">{number}</span>
      <h3 className="mt-4 font-display text-[clamp(1.6rem,2.6vw,2.4rem)] leading-[1.05] font-[380] tracking-[-0.02em]">{title}</h3>
      <p className="mt-4 text-[15px] leading-relaxed opacity-70">{text}</p>
    </motion.div>
  )
}

export function StoryScroll() {
  const ref = useRef<HTMLElement>(null)
  const reduceMotion = useReducedMotion()
  const { scrollYProgress: progress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  // Тяжёлая сцена готовится заранее — в свободное время браузера после загрузки
  // (или когда секция приближается), и дальше остаётся смонтированной.
  // Так при прокрутке нет всплесков нагрузки на входе в сцену.
  const approaching = useInView(ref, { margin: '150% 0px 150% 0px' })
  const [near, setNear] = useState(false)
  useEffect(() => {
    if (approaching) setNear(true)
  }, [approaching])
  useEffect(() => {
    const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1200))
    const cancel = window.cancelIdleCallback ?? window.clearTimeout
    const handle = idle(() => setNear(true), { timeout: 2500 })
    return () => cancel(handle)
  }, [])
  const [stageRef, stage] = useElementSize<HTMLDivElement>()
  const lines = useDocument()
  const headings = lines.filter((l) => l.heading).map((l) => l.text).slice(0, 5)
  const { gallery, title, slideCount } = useMemo(getShowcase, [])
  const ringScenes = gallery.slice(0, 6)

  // Фон «перетекает» в чернила на время карусели и возвращается к бумаге в финале.
  // Меняется прозрачность чёрного слоя, а не цвет фона, — это почти бесплатно для видеокарты.
  const inkOpacity = useTransform(progress, [0.36, 0.46, 0.84, 0.94], [0, 1, 1, 0])
  const color = useTransform(progress, [0.36, 0.46, 0.84, 0.94], [INK, PAPER, PAPER, INK])
  const ringRotate = useTransform(progress, (p) => lerp(18, -342, ease(segment(p, 0.46, 0.86))))
  const ringTilt = useTransform(progress, (p) => lerp(-12, 0, segment(p, 0.84, 0.94)))
  const fileOpacity = useTransform(progress, (p) => segment(p, 0.92, 0.97))
  const fileY = useTransform(progress, (p) => lerp(60, 0, ease(segment(p, 0.92, 0.98))))
  const progressLine = useTransform(progress, [0, 1], [0, 1])

  const cardWidth = Math.min(Math.max(stage.width * 0.26, 220), 380)
  const radius = Math.min(stage.width * 0.32, 470)

  if (reduceMotion) {
    return (
      <section className="mx-auto w-full max-w-[1280px] px-5 py-20 sm:px-8" aria-label="Как это работает">
        <p className="font-display text-[2rem] italic">Текст доклада → слайды → готовый PPTX</p>
      </section>
    )
  }

  return (
    <section ref={ref} className="relative h-[460vh] bg-background" aria-label="Как это работает">
      <div className="sticky top-0 h-dvh overflow-hidden">
        <motion.div aria-hidden className="absolute inset-0 bg-foreground will-change-[opacity]" style={{ opacity: inkOpacity }} />
        <div className="relative mx-auto h-full w-full max-w-[1280px] px-5 sm:px-8">
          {/* Главы слева */}
          <div className="absolute top-[18vh] left-5 z-20 sm:left-8">
            <Chapter progress={progress} from={0} to={0.36} number="01" title="Вы вставляете доклад" text="Текст выступления, тезисы или план — как есть, без подготовки." color={color} />
            <Chapter progress={progress} from={0.36} to={0.86} number="02" title="Ассистент выстраивает слайды" text="Разделы становятся слайдами, мысли — пунктами, сравнения — колонками." color={color} />
            <Chapter progress={progress} from={0.86} to={1.5} number="03" title="Вы скачиваете PPTX" text="Настоящий файл PowerPoint в едином оформлении — каждое слово редактируется." color={color} />
          </div>

          {/* Сцена */}
          <div ref={stageRef} className="absolute inset-0 [perspective:1800px]">
            {near && stage.width > 0 && (
              <>
                <DocumentSheet progress={progress} lines={lines} />
                {headings.map((text, i) => (
                  <Fragment key={text} progress={progress} index={i} text={text} />
                ))}
                <motion.div
                  className="absolute top-1/2 left-[58%] h-0 w-0 will-change-transform [transform-style:preserve-3d] max-md:left-1/2"
                  style={{ rotateY: ringRotate, rotateX: ringTilt }}
                >
                  {ringScenes.map((scene, i) => (
                    <RingCard key={i} progress={progress} scene={scene} index={i} count={ringScenes.length} radius={radius} width={cardWidth} />
                  ))}
                </motion.div>

                {/* Готовый файл */}
                <motion.div
                  style={{ opacity: fileOpacity, y: fileY }}
                  className="absolute bottom-[12vh] left-[58%] flex -translate-x-1/2 items-center gap-4 border border-foreground bg-background px-5 py-3.5 max-md:left-1/2"
                >
                  <span className="flex h-10 w-8 items-end justify-center bg-foreground pb-1 font-sans text-[8px] font-bold tracking-wider text-background">PPTX</span>
                  <span className="flex flex-col">
                    <span className="font-display text-[17px] leading-tight">{title}.pptx</span>
                    <span className="eyebrow mt-1 !text-[10px]">{slideCount} {plural(slideCount, ['слайд', 'слайда', 'слайдов'])} · 16:9 · редактируемый</span>
                  </span>
                </motion.div>
              </>
            )}
          </div>

          {/* Шкала прогресса справа */}
          <div className="absolute top-[20vh] right-5 bottom-[20vh] w-px bg-current opacity-20 sm:right-8" aria-hidden />
          <motion.div style={{ scaleY: progressLine, color }} className="absolute top-[20vh] right-5 bottom-[20vh] w-px origin-top bg-current sm:right-8" aria-hidden />
        </div>
      </div>
    </section>
  )
}
