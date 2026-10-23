import { useEffect, useMemo, useState, type PointerEvent } from 'react'
import { animate, motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'motion/react'
import type { SlideScene } from '@/layouts/scene'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { useElementSize } from '@/hooks/useElementSize'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { getShowcase } from './showcase'
import { PaperSheet } from '@/components/app/PaperSheet'

const INTERVAL_MS = 3800
/** Слайды примера в колоде: разные по виду */
const DECK_ORDER = [0, 2, 3, 1]
/** Ширина карточки относительно колонки */
const CARD_RATIO = 0.8

/** Положение карточки по месту в колоде: 0 — верхняя, дальше — выглядывающие сзади */
const POSITIONS = [
  { x: 0, y: 0, rotate: -0.6, scale: 1 },
  { x: 34, y: -34, rotate: 3, scale: 0.955 },
  { x: -30, y: -64, rotate: -3.8, scale: 0.915 },
  { x: 10, y: -90, rotate: 1.6, scale: 0.875 },
]

/** Длительность перекладывания: подъём из-за колоды, переход наверх, укладка */
const PULL_DURATION = 1.6
/** Доля времени, когда лист уже над колодой и переходит на передний план */
const SWAP_AT = 0.44

interface DeckCardProps {
  scene: SlideScene
  rank: number
  /** Лист только что вытащен из-под колоды и кладётся сверху */
  pulled: boolean
  step: number
  count: number
  cardWidth: number
  cardHeight: number
  scale: number
  reduceMotion: boolean
}

function DeckCard({ scene, rank, pulled, step, count, cardWidth, cardHeight, scale, reduceMotion }: DeckCardProps) {
  const bend = useMotionValue(0)
  // Пока лист поднимается, он ещё позади колоды; наверх переходит, когда уже над ней.
  // Храним шаг, на котором лист «перешёл наверх», — без лишнего кадра поверх колоды.
  const [surfacedAt, setSurfacedAt] = useState(0)
  const behind = pulled && surfacedAt !== step && !reduceMotion
  const target = POSITIONS[rank]
  const back = POSITIONS[count - 1]
  const liftY = back.y - cardHeight * 0.5

  useEffect(() => {
    if (step === 0 || reduceMotion) return
    if (pulled) {
      const timer = window.setTimeout(() => setSurfacedAt(step), PULL_DURATION * SWAP_AT * 1000)
      // Лист гнётся: нижний край отстаёт при подъёме, при укладке пружинит и распрямляется
      const controls = animate(bend, [0, 42, 34, -10, 4, 0], {
        duration: PULL_DURATION,
        times: [0, 0.28, SWAP_AT, 0.74, 0.88, 1],
        ease: 'easeInOut',
      })
      return () => {
        window.clearTimeout(timer)
        controls.stop()
      }
    }
    // Остальные листы чуть «вздыхают», когда их сдвигают назад
    const controls = animate(bend, [0, -6, 0], { duration: 0.9, delay: 0.55, ease: 'easeInOut' })
    return () => controls.stop()
  }, [step, pulled, reduceMotion, bend])

  const zIndex = behind ? 5 : 50 - rank * 10
  const animating = pulled && step > 0 && !reduceMotion

  return (
    <motion.div
      className="absolute bottom-[6%] left-1/2"
      style={{
        width: cardWidth,
        height: cardHeight,
        marginLeft: -cardWidth / 2,
        transformOrigin: '50% 100%',
        zIndex,
        // Своё 3D-пространство у каждой карточки: изгиб рисуется внутри неё,
        // а в колоду карточка ложится плоским слоем — листы не прорезают друг друга
        perspective: 1100,
        transformStyle: 'flat',
        isolation: 'isolate',
        // Тень повторяет реальную форму листа, в том числе изогнутого
        filter: 'drop-shadow(0 1px 1px rgb(20 20 20 / 0.06)) drop-shadow(0 18px 22px rgb(20 20 20 / 0.16))',
      }}
      initial={{ opacity: 0, y: 70, x: target.x, rotate: target.rotate * 2.5, scale: target.scale }}
      animate={
        animating
          ? {
              // вверх из-за колоды → над колодой → вниз, поверх первой карточки
              x: [back.x, back.x + 26, back.x + 26, target.x],
              y: [back.y, liftY, liftY, target.y],
              rotate: [back.rotate, 5, 5, target.rotate],
              scale: [back.scale, 0.985, 0.985, target.scale],
              opacity: 1,
            }
          : { ...target, opacity: 1 }
      }
      transition={
        animating
          ? { duration: PULL_DURATION, times: [0, SWAP_AT - 0.04, SWAP_AT, 1], ease: [EASE_OUT_EXPO, 'linear', EASE_OUT_EXPO] }
          : {
              duration: step === 0 ? 1.1 : 0.9,
              ease: EASE_OUT_EXPO,
              // При открытии листы ложатся по очереди; при перекладывании — уступают место,
              // когда верхний лист уже поднят над колодой
              delay: step === 0 ? 0.25 + (count - 1 - rank) * 0.14 : PULL_DURATION * SWAP_AT,
            }
      }
    >
      <PaperSheet width={cardWidth} height={cardHeight} bend={bend}>
        {() => <SlideRenderer scene={scene} scale={scale} />}
      </PaperSheet>
    </motion.div>
  )
}

/**
 * Колода настоящих слайдов демо-презентации на главном экране.
 * По кругу самая дальняя карточка вытаскивается из-за колоды
 * и ложится поверх первой, остальные сдвигаются на шаг назад.
 */
export function HeroShowcase() {
  const { gallery, title, slideCount } = useMemo(getShowcase, [])
  const deck = useMemo(() => DECK_ORDER.map((i) => ({ index: i, scene: gallery[i] })).filter((d) => d.scene), [gallery])
  const [ref, size] = useElementSize<HTMLDivElement>()
  const [step, setStep] = useState(0)
  const [paused, setPaused] = useState(false)
  const reduceMotion = useReducedMotion()

  const px = useMotionValue(0)
  const py = useMotionValue(0)
  const rotateY = useSpring(useTransform(px, [-0.5, 0.5], [-5, 5]), { stiffness: 90, damping: 20 })
  const rotateX = useSpring(useTransform(py, [-0.5, 0.5], [4, -4]), { stiffness: 90, damping: 20 })

  // Перекладывание по таймеру. Пауза — только пока колода в фокусе клавиатуры.
  // Ручной клик перезапускает отсчёт, чтобы следующая карточка не пошла сразу.
  useEffect(() => {
    if (paused) return
    const timer = window.setInterval(() => setStep((s) => s + 1), reduceMotion ? INTERVAL_MS * 1.5 : INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [paused, reduceMotion, step])

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    px.set((event.clientX - rect.left) / rect.width - 0.5)
    py.set((event.clientY - rect.top) / rect.height - 0.5)
  }

  const count = deck.length
  const cardWidth = size.width * CARD_RATIO
  const cardHeight = (cardWidth * 9) / 16
  const scale = cardWidth / SLIDE_PX.width
  // Место карточки i в колоде: с каждым шагом последняя становится первой
  const rankOf = (i: number) => (i + step) % count
  const topCard = deck.find((_, i) => rankOf(i) === 0) ?? deck[0]
  const advance = () => setStep((s) => s + 1)

  return (
    <figure className="flex w-full flex-col">
      <div
        ref={ref}
        role="button"
        tabIndex={0}
        aria-label="Показать следующий слайд примера"
        onClick={(e) => {
          advance()
          // Клик мышью не должен ставить колоду на паузу через фокус
          if (e.detail > 0) e.currentTarget.blur()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            advance()
          }
        }}
        onFocus={() => setPaused(true)}
        onBlur={() => setPaused(false)}
        onPointerMove={onPointerMove}
        onPointerLeave={() => {
          px.set(0)
          py.set(0)
        }}
        className="relative aspect-[16/11.5] w-full cursor-pointer outline-none [perspective:1600px] focus-visible:ring-1 focus-visible:ring-foreground focus-visible:ring-offset-8 focus-visible:ring-offset-background"
      >
        {size.width > 0 && (
          <motion.div style={{ rotateX, rotateY }} className="absolute inset-0">
            {deck.map((card, i) => {
              const rank = rankOf(i)
              return (
                <DeckCard
                  key={card.index}
                  scene={card.scene}
                  rank={rank}
                  pulled={rank === 0 && step > 0}
                  step={step}
                  count={count}
                  cardWidth={cardWidth}
                  cardHeight={cardHeight}
                  scale={scale}
                  reduceMotion={Boolean(reduceMotion)}
                />
              )
            })}
          </motion.div>
        )}
        {/* Мягкая тень колоды на «столе» */}
        <div className="pointer-events-none absolute right-[16%] bottom-[3%] left-[16%] h-6 rounded-[50%] bg-foreground/15 blur-xl" aria-hidden />
      </div>

      <motion.figcaption
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.9, delay: 0.9, ease: EASE_OUT_EXPO }}
        className="mt-6 flex items-baseline justify-between gap-6 border-t border-border pt-3"
      >
        <span className="font-display text-[15px] leading-snug text-foreground/80 italic">
          Рис. 1 — «{title}», сгенерировано из текста доклада
        </span>
        <span className="eyebrow shrink-0 tabular-nums" aria-live="polite">
          {String(topCard.index + 1).padStart(2, '0')} / {String(slideCount).padStart(2, '0')}
        </span>
      </motion.figcaption>
    </figure>
  )
}
