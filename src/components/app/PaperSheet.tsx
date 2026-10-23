import type { ReactNode } from 'react'
import { motion, useTransform, type MotionValue } from 'motion/react'

const SLICES = 10

interface PaperSheetProps {
  width: number
  height: number
  /** Общий угол изгиба листа в градусах: 0 — плоский, >0 — нижний край отгибается */
  bend: MotionValue<number>
  /** Содержимое листа. Рисуется в каждой полосе и обрезается по ней. */
  children: () => ReactNode
}

/** Доля изгиба на полосе: у верхнего края почти ноль, к нижнему — сильнее, как у бумаги */
const WEIGHTS = Array.from({ length: SLICES }, (_, i) => Math.pow((i + 1) / SLICES, 1.6))
const WEIGHT_SUM = WEIGHTS.reduce((a, b) => a + b, 0)

function Slice({ index, width, height, bend, children }: { index: number; width: number; height: number; bend: MotionValue<number>; children: () => ReactNode }) {
  const sliceHeight = height / SLICES
  const rotateX = useTransform(bend, (b) => (index === 0 ? 0 : (b * WEIGHTS[index]) / WEIGHT_SUM))
  // Тень изгиба: непрерывный градиент от верха полосы к низу, без ступенек между полосами
  const shadeAt = (b: number, position: number) => Math.min(0.16, (Math.abs(b) / 42) * Math.pow(position, 1.8) * 0.16)
  const shade = useTransform(
    bend,
    (b) =>
      `linear-gradient(to bottom, rgb(20 20 20 / ${shadeAt(b, index / SLICES)}), rgb(20 20 20 / ${shadeAt(b, (index + 1) / SLICES)}))`,
  )

  return (
    <motion.div
      className="absolute left-0"
      style={{
        top: index === 0 ? 0 : sliceHeight,
        width,
        height: sliceHeight,
        rotateX,
        transformOrigin: '50% 0%',
        transformStyle: 'preserve-3d',
      }}
    >
      <div className="absolute inset-x-0 top-0 overflow-hidden bg-white" style={{ height: sliceHeight + 0.6 }}>
        <div className="absolute left-0" style={{ top: -index * sliceHeight, width, height }}>
          {children()}
        </div>
        <motion.div className="pointer-events-none absolute inset-0" style={{ background: shade }} />
      </div>
      {index < SLICES - 1 && (
        <Slice index={index + 1} width={width} height={height} bend={bend}>
          {children}
        </Slice>
      )}
    </motion.div>
  )
}

/**
 * Лист, который умеет гнуться. Разрезан на горизонтальные полосы,
 * сцепленные как шарниры: каждая повёрнута чуть сильнее предыдущей,
 * поэтому лист выгибается плавной дугой, а не наклоняется целиком.
 */
export function PaperSheet({ width, height, bend, children }: PaperSheetProps) {
  return (
    <div className="relative" style={{ width, height, transformStyle: 'preserve-3d' }}>
      <Slice index={0} width={width} height={height} bend={bend}>
        {children}
      </Slice>
    </div>
  )
}
