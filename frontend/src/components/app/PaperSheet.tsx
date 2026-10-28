import { memo, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { motion, useMotionValueEvent, useTransform, type MotionValue } from 'motion/react'

const SLICES = 8
/** Ниже этого угла лист считается ровным */
const FLAT_EPSILON = 0.5

/** Тень в покое — дешёвая box-shadow; при изгибе — drop-shadow, повторяющая форму листа */
const FLAT_SHADOW = '0 1px 1px rgb(20 20 20 / 0.06), 0 18px 28px -14px rgb(20 20 20 / 0.28)'
const BENT_SHADOW = 'drop-shadow(0 1px 1px rgb(20 20 20 / 0.06)) drop-shadow(0 18px 22px rgb(20 20 20 / 0.16))'

interface PaperSheetProps {
  width: number
  height: number
  /** Общий угол изгиба листа в градусах: 0 — плоский, >0 — нижний край отгибается */
  bend: MotionValue<number>
  /**
   * Содержимое листа. Передавайте мемоизированный элемент (useMemo):
   * снимок для изгиба пересоздаётся, только когда содержимое изменилось.
   */
  children: ReactNode
  /** Рисовать тень листа (по умолчанию да) */
  shadow?: boolean
}

/** Доля изгиба на полосе: у верхнего края почти ноль, к нижнему — сильнее, как у бумаги */
const WEIGHTS = Array.from({ length: SLICES }, (_, i) => Math.pow((i + 1) / SLICES, 1.6))
const WEIGHT_SUM = WEIGHTS.reduce((a, b) => a + b, 0)

const shadeAt = (b: number, position: number) => Math.min(0.16, (Math.abs(b) / 42) * Math.pow(position, 1.8) * 0.16)

/**
 * Снимок содержимого листа в SVG-картинку (через foreignObject).
 * Полосы изгиба показывают кусочки одной картинки вместо восьми копий
 * DOM-дерева слайда — это в разы дешевле. Стили слайдов заданы inline,
 * поэтому снимок выглядит так же, как живой слайд.
 */
function snapshot(node: HTMLElement, width: number, height: number): string | null {
  try {
    // Снимаем с копии: сам плоский слой в этот момент уже скрыт на время изгиба
    const clone = node.cloneNode(true) as HTMLElement
    clone.style.visibility = 'visible'
    const html = new XMLSerializer().serializeToString(clone)
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><foreignObject width="100%" height="100%">${html}</foreignObject></svg>`
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  } catch {
    return null
  }
}

interface SliceProps {
  index: number
  width: number
  height: number
  bend: MotionValue<number>
  image: string | null
  children: ReactNode
}

const Slice = memo(function Slice({ index, width, height, bend, image, children }: SliceProps) {
  const sliceHeight = height / SLICES
  const rotateX = useTransform(bend, (b) => (index === 0 ? 0 : (b * WEIGHTS[index]) / WEIGHT_SUM))
  // Тень изгиба: непрерывный градиент от верха полосы к низу, без ступенек между полосами
  const shade = useTransform(
    bend,
    (b) => `linear-gradient(to bottom, rgb(20 20 20 / ${shadeAt(b, index / SLICES)}), rgb(20 20 20 / ${shadeAt(b, (index + 1) / SLICES)}))`,
  )

  return (
    <motion.div
      className="absolute left-0"
      style={{ top: index === 0 ? 0 : sliceHeight, width, height: sliceHeight, rotateX, transformOrigin: '50% 0%', transformStyle: 'preserve-3d' }}
    >
      {/* Полоса заходит на следующую с запасом — стыки не просвечивают при изгибе */}
      {image ? (
        <div
          className="absolute inset-x-0 top-0 bg-white"
          style={{
            height: sliceHeight + 2,
            backgroundImage: `url("${image}")`,
            backgroundSize: `${width}px ${height}px`,
            backgroundPosition: `0 ${-index * sliceHeight}px`,
            backgroundRepeat: 'no-repeat',
          }}
        >
          <motion.div className="pointer-events-none absolute inset-0" style={{ background: shade }} />
        </div>
      ) : (
        <div className="absolute inset-x-0 top-0 overflow-hidden bg-white" style={{ height: sliceHeight + 2 }}>
          <div className="absolute left-0" style={{ top: -index * sliceHeight, width, height }}>
            {children}
          </div>
          <motion.div className="pointer-events-none absolute inset-0" style={{ background: shade }} />
        </div>
      )}
      {index < SLICES - 1 && (
        <Slice index={index + 1} width={width} height={height} bend={bend} image={image}>
          {children}
        </Slice>
      )}
    </motion.div>
  )
})

/**
 * Лист, который умеет гнуться. На время изгиба он разрезается на
 * горизонтальные полосы, сцепленные как шарниры: каждая повёрнута чуть
 * сильнее предыдущей, поэтому лист выгибается плавной дугой. В покое
 * лист рисуется одним слоем — без стыков и без лишней нагрузки.
 */
export function PaperSheet({ width, height, bend, children, shadow = true }: PaperSheetProps) {
  const flatRef = useRef<HTMLDivElement>(null)
  const [bending, setBending] = useState(() => Math.abs(bend.get()) >= FLAT_EPSILON)
  const [shot, setShot] = useState<{ content: ReactNode; width: number; image: string | null } | null>(null)

  useMotionValueEvent(bend, 'change', (b) => {
    const next = Math.abs(b) >= FLAT_EPSILON
    setBending((current) => (current === next ? current : next))
  })

  // Снимок делается в момент начала изгиба — и только если содержимое изменилось
  useLayoutEffect(() => {
    if (!bending || !flatRef.current) return
    if (shot && shot.content === children && shot.width === width) return
    setShot({ content: children, width, image: snapshot(flatRef.current, width, height) })
  }, [bending, children, width, height, shot])

  const image = shot && shot.content === children && shot.width === width ? shot.image : null

  return (
    <div
      className="relative"
      style={{
        width,
        height,
        perspective: 1100,
        boxShadow: shadow && !bending ? FLAT_SHADOW : undefined,
        filter: shadow && bending ? BENT_SHADOW : undefined,
      }}
    >
      {/* Плоский слой всегда в DOM: его видно в покое, и с него снимается картинка для изгиба */}
      <div ref={flatRef} className="absolute inset-0 overflow-hidden bg-white" style={{ visibility: bending ? 'hidden' : 'visible' }}>
        {children}
      </div>
      {bending && (
        <div className="absolute inset-0" style={{ transformStyle: 'preserve-3d' }}>
          <Slice index={0} width={width} height={height} bend={bend} image={image}>
            {children}
          </Slice>
        </div>
      )}
    </div>
  )
}
