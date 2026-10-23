import { memo, type CSSProperties } from 'react'
import type { SceneElement, SceneText, SlideScene } from '@/layouts/scene'
import { LINE_HEIGHT_FACTOR } from '@/layouts/text-fit'
import { presentationTheme } from '@/theme/presentation-theme'
import { cn } from '@/lib/utils'

/** 1 дюйм слайда = 96 px превью. Слайд 13.333″ × 7.5″ → 1280 × 720 px. */
export const PX_PER_INCH = 96
const PX_PER_PT = PX_PER_INCH / 72

export const SLIDE_PX = {
  width: Math.round(presentationTheme.slide.width * PX_PER_INCH),
  height: Math.round(presentationTheme.slide.height * PX_PER_INCH),
}

interface SlideRendererProps {
  scene: SlideScene
  /** Масштаб относительно 1280 × 720 */
  scale: number
  /** Показывать подсказки в пустых полях (в редакторе) */
  showPlaceholders?: boolean
  /** Подсветка поля, которое сейчас редактируется */
  activeField?: string | null
  /** Клик по текстовому полю на слайде */
  onFieldClick?: (field: string) => void
  className?: string
}

const px = (inches: number) => `${inches * PX_PER_INCH}px`

function boxStyle(element: SceneElement): CSSProperties {
  return { position: 'absolute', left: px(element.box.x), top: px(element.box.y), width: px(element.box.w), height: px(element.box.h) }
}

const VALIGN = { top: 'flex-start', middle: 'center', bottom: 'flex-end' } as const

function TextElement({
  element,
  showPlaceholder,
  active,
  onClick,
}: {
  element: SceneText
  showPlaceholder: boolean
  active: boolean
  onClick?: () => void
}) {
  const { style } = element
  const empty = element.paragraphs.length === 0
  if (empty && !(showPlaceholder && element.placeholder)) return null

  const fontSizePx = style.fontSize * PX_PER_PT
  const paragraphs = empty ? [{ text: element.placeholder ?? '' }] : element.paragraphs
  const interactive = Boolean(onClick)

  return (
    <div
      data-field={element.field}
      onClick={onClick}
      style={{
        ...boxStyle(element),
        display: 'flex',
        flexDirection: 'column',
        justifyContent: VALIGN[style.valign],
        fontFamily: `'${style.fontFace}', ${presentationTheme.fonts.cssFallback}`,
        fontSize: `${fontSizePx}px`,
        fontWeight: style.bold ? 700 : 400,
        lineHeight: LINE_HEIGHT_FACTOR * style.lineSpacing,
        color: style.color,
        textAlign: style.align,
        whiteSpace: 'pre-wrap',
        overflowWrap: 'break-word',
        opacity: empty ? 0.38 : 1,
      }}
      className={cn(
        'rounded-[3px] outline-offset-[6px]',
        interactive && 'cursor-text hover:outline-1 hover:outline-dashed hover:outline-[#141414]/40',
        active && 'outline-1 outline-solid !outline-[#141414]/70',
        element.overflow && 'outline-1 outline-dashed !outline-[#a32020]/80',
      )}
    >
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          style={{
            margin: 0,
            marginBottom: index < paragraphs.length - 1 ? `${style.paragraphSpacing * PX_PER_PT}px` : 0,
            position: 'relative',
            paddingLeft: paragraph.bullet ? `${(style.bulletIndent ?? 0) * PX_PER_PT}px` : 0,
          }}
        >
          {paragraph.bullet && (
            <span aria-hidden style={{ position: 'absolute', left: 0 }}>
              •
            </span>
          )}
          {paragraph.text}
        </p>
      ))}
    </div>
  )
}

/**
 * Рендер «сцены» слайда в браузере. Тот же набор элементов уходит в PPTX,
 * поэтому превью соответствует итоговому файлу.
 */
export const SlideRenderer = memo(function SlideRenderer({
  scene,
  scale,
  showPlaceholders = false,
  activeField = null,
  onFieldClick,
  className,
}: SlideRendererProps) {
  return (
    <div
      className={cn('relative overflow-hidden', className)}
      style={{ width: SLIDE_PX.width * scale, height: SLIDE_PX.height * scale }}
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: SLIDE_PX.width,
          height: SLIDE_PX.height,
          transform: `scale(${scale})`,
          transformOrigin: '0 0',
          background: scene.background,
        }}
      >
        {scene.elements.map((element, index) => {
          if (element.type === 'rect') return <div key={index} style={{ ...boxStyle(element), background: element.fill }} />
          if (element.type === 'image')
            return <img key={index} src={element.src} alt="" style={{ ...boxStyle(element), objectFit: 'contain', objectPosition: 'right center' }} />
          return (
            <TextElement
              key={index}
              element={element}
              showPlaceholder={showPlaceholders}
              active={activeField === element.field}
              onClick={onFieldClick && element.placeholder !== undefined ? () => onFieldClick(element.field) : undefined}
            />
          )
        })}
      </div>
    </div>
  )
})
