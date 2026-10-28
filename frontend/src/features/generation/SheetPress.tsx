import { useEffect, useMemo, useState } from 'react'
import { animate, motion, useMotionValue, useReducedMotion } from 'motion/react'
import { PaperSheet } from '@/components/app/PaperSheet'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { useElementSize } from '@/hooks/useElementSize'
import { presentationTheme } from '@/theme/presentation-theme'

/**
 * Экран загрузки: «печатный станок». Новый лист прилетает и, изгибаясь,
 * ложится на стопку; на нём проступает макет слайда — заголовок, пункты,
 * колонки. Прежние листы уходят вглубь стопки. Чисто декоративный элемент,
 * о реальном прогрессе генерации ничего не говорит.
 */

const CYCLE_MS = 3200
const CARD_RATIO = 0.78
const VISIBLE = 4
/** Сколько готовых листов уже лежит на столе при открытии экрана */
const SEEDED = 2

type Kind = 'title' | 'bullets' | 'columns' | 'text'
const KINDS: Kind[] = ['title', 'bullets', 'columns', 'text']

const PILE = [
  { x: 0, y: 0, rotate: -0.8, scale: 1, opacity: 1 },
  { x: 30, y: -30, rotate: 2.8, scale: 0.955, opacity: 1 },
  { x: -28, y: -58, rotate: -3.6, scale: 0.915, opacity: 1 },
  { x: 8, y: -80, rotate: 1.4, scale: 0.875, opacity: 0 },
]

const { colors } = presentationTheme

/** Полоска, которая «пропечатывается» слева направо */
function Ink({ className, style, delay, active }: { className: string; style?: React.CSSProperties; delay: number; active: boolean }) {
  return (
    <motion.span
      className={`block origin-left ${className}`}
      style={style}
      initial={false}
      animate={{ scaleX: active ? 1 : 0, opacity: active ? 1 : 0 }}
      transition={{ duration: active ? 0.7 : 0, delay: active ? delay : 0, ease: EASE_OUT_EXPO }}
    />
  )
}

/** Схема слайда, проступающая на листе. Пропорции — как у макетов из реестра. */
function SheetContent({ kind, inked }: { kind: Kind; inked: boolean }) {
  const t = (i: number) => 0.15 + i * 0.12
  if (kind === 'title') {
    return (
      <div className="absolute inset-0 flex flex-col justify-end px-[7%] pb-[16%]" style={{ background: inked ? colors.primary : '#fff', transition: 'background 0.9s cubic-bezier(0.16,1,0.3,1)' }}>
        <Ink active={inked} delay={t(1)} className="mb-[4%] h-[1.4%] w-[9%]" style={{ background: colors.accentOnPrimary }} />
        <Ink active={inked} delay={t(2)} className="h-[7%] w-[66%]" style={{ background: '#ffffff' }} />
        <Ink active={inked} delay={t(3)} className="mt-[3%] h-[3.2%] w-[42%]" style={{ background: colors.textOnPrimaryMuted }} />
        <span className="absolute inset-x-0 bottom-0 h-[2.5%]" style={{ background: inked ? colors.accent : 'transparent', transition: 'background 0.9s' }} />
      </div>
    )
  }
  const heading = (
    <>
      <Ink active={inked} delay={t(0)} className="h-[1.4%] w-[7%]" style={{ background: colors.accent }} />
      <Ink active={inked} delay={t(1)} className="mt-[2.4%] h-[5.5%] w-[48%]" style={{ background: colors.primary }} />
    </>
  )
  const line = (width: string, i: number, bullet = true) => (
    <div key={i} className="flex items-center gap-[2%]" style={{ height: '4.2%' }}>
      {bullet && <Ink active={inked} delay={t(2 + i)} className="aspect-square h-[55%] rounded-full" style={{ background: colors.text }} />}
      <Ink active={inked} delay={t(2 + i) + 0.05} className="h-[60%]" style={{ width, background: '#c9ced6' }} />
    </div>
  )
  return (
    <div className="absolute inset-0 flex flex-col px-[7%] pt-[8%] pb-[7%]">
      {heading}
      {kind === 'bullets' && <div className="mt-[7%] flex flex-col gap-[3.4%]">{['82%', '64%', '74%', '52%', '68%'].map((w, i) => line(w, i))}</div>}
      {kind === 'text' && <div className="mt-[7%] flex flex-col gap-[2.6%]">{['92%', '88%', '94%', '60%', '0%', '90%', '72%'].map((w, i) => line(w, i, false))}</div>}
      {kind === 'columns' && (
        <div className="mt-[7%] grid flex-1 grid-cols-2 gap-[6%]">
          {[0, 1].map((col) => (
            <div key={col} className="flex flex-col gap-[5%]" style={{ borderLeft: col ? `1px solid ${inked ? colors.divider : 'transparent'}` : undefined, paddingLeft: col ? '6%' : 0 }}>
              <Ink active={inked} delay={t(2 + col)} className="h-[5%] w-[40%]" style={{ background: colors.accent }} />
              {['88%', '70%', '80%'].map((w, i) => (
                <div key={i} className="flex items-center gap-[3%]" style={{ height: '5.5%' }}>
                  <Ink active={inked} delay={t(3 + i + col)} className="aspect-square h-[55%] rounded-full" style={{ background: colors.text }} />
                  <Ink active={inked} delay={t(3 + i + col) + 0.05} className="h-[60%]" style={{ width: w, background: '#c9ced6' }} />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      <Ink active={inked} delay={t(8)} className="mt-auto h-px w-full" style={{ background: colors.divider }} />
    </div>
  )
}

function Sheet({ id, rank, cardWidth, cardHeight, reduceMotion }: { id: number; rank: number; cardWidth: number; cardHeight: number; reduceMotion: boolean }) {
  // Листы стартовой стопки уже «отпечатаны» и просто ложатся на стол
  const seeded = id < SEEDED
  const bend = useMotionValue(reduceMotion || seeded ? 0 : 40)
  const [inked, setInked] = useState(reduceMotion || seeded)
  const target = PILE[Math.min(rank, PILE.length - 1)]

  useEffect(() => {
    if (reduceMotion || seeded) return
    // Лист гнётся в полёте и пружинит при укладке, затем на нём проступает макет
    const controls = animate(bend, [40, 22, -9, 3, 0], { duration: 1.25, times: [0, 0.35, 0.62, 0.84, 1], ease: 'easeInOut' })
    // Печать начинается, когда лист уже лёг: изгиб закончился и лист рисуется одним слоем
    const timer = window.setTimeout(() => setInked(true), 1300)
    return () => {
      controls.stop()
      window.clearTimeout(timer)
    }
  }, [bend, reduceMotion, seeded])

  // Листы, уходящие вглубь стопки, слегка «вздыхают»
  useEffect(() => {
    if (rank === 0 || reduceMotion) return
    const controls = animate(bend, [0, -5, 0], { duration: 0.9, ease: 'easeInOut' })
    return () => controls.stop()
  }, [rank, bend, reduceMotion])

  const fromLeft = id % 2 === 0
  const printing = inked && rank === 0 && !reduceMotion
  // Содержимое листа создаётся один раз на состояние — полосы изгиба его не перерисовывают
  const content = useMemo(() => <SheetFace id={id} inked={inked} printing={printing} />, [id, inked, printing])

  return (
    <motion.div
      className="absolute bottom-[8%] left-1/2"
      style={{
        width: cardWidth,
        height: cardHeight,
        marginLeft: -cardWidth / 2,
        zIndex: 100 + id,
        transformOrigin: '50% 100%',
        perspective: 1100,
        isolation: 'isolate',
      }}
      initial={
        reduceMotion
          ? { opacity: 0 }
          : seeded
            ? { ...target, y: target.y + 24, opacity: 0 }
            : { x: fromLeft ? -cardWidth * 0.75 : cardWidth * 0.75, y: -cardHeight * 0.55, rotate: fromLeft ? -12 : 11, scale: 1.03, opacity: 0 }
      }
      animate={target}
      transition={{ duration: rank === 0 ? 1.15 : 0.9, ease: EASE_OUT_EXPO, delay: seeded ? 0.15 + id * 0.12 : id === SEEDED ? 0.45 : 0 }}
    >
      <PaperSheet width={cardWidth} height={cardHeight} bend={bend}>
        {content}
      </PaperSheet>
    </motion.div>
  )
}

function SheetFace({ id, inked, printing }: { id: number; inked: boolean; printing: boolean }) {
  return (
    <div className="relative size-full overflow-hidden bg-white">
      <SheetContent kind={KINDS[id % KINDS.length]} inked={inked} />
      {/* Линия печати проходит по листу один раз, пока проступает макет */}
      {printing && (
        <motion.span
          className="absolute inset-x-0 h-[2px] bg-[linear-gradient(90deg,transparent,rgb(20_20_20/0.35),transparent)]"
          initial={{ top: '0%', opacity: 0 }}
          animate={{ top: ['0%', '100%'], opacity: [0, 1, 1, 0] }}
          transition={{ duration: 1.5, ease: [0.65, 0, 0.35, 1] }}
        />
      )}
    </div>
  )
}

export function SheetPress() {
  const [ref, size] = useElementSize<HTMLDivElement>()
  const reduceMotion = Boolean(useReducedMotion())
  const [top, setTop] = useState(SEEDED)

  useEffect(() => {
    const timer = window.setInterval(() => setTop((t) => t + 1), reduceMotion ? CYCLE_MS * 1.5 : CYCLE_MS)
    return () => window.clearInterval(timer)
  }, [reduceMotion])

  const cardWidth = size.width * CARD_RATIO
  const cardHeight = (cardWidth * 9) / 16
  const ids = Array.from({ length: VISIBLE }, (_, i) => top - i).filter((id) => id >= 0)

  return (
    <div ref={ref} aria-hidden className="relative mx-auto aspect-[16/12] w-full max-w-[640px]">
      {size.width > 0 && ids.map((id) => <Sheet key={id} id={id} rank={top - id} cardWidth={cardWidth} cardHeight={cardHeight} reduceMotion={reduceMotion} />)}
      <div className="pointer-events-none absolute right-[16%] bottom-[5%] left-[16%] h-6 rounded-[50%] bg-foreground/15 blur-xl" />
    </div>
  )
}
