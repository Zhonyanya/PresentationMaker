import { motion } from 'motion/react'
import type { SlideLayout } from '@/domain/presentation'
import { layoutList } from '@/layouts/registry'
import { readableColor, type PresentationTheme } from '@/theme/presentation-theme'
import { cn } from '@/lib/utils'

/** Схематичные миниатюры макетов. Для новых макетов без схемы показывается иконка из реестра. */
type LayoutColors = PresentationTheme['colors']
const SCHEMATICS: Partial<Record<SlideLayout, (colors: LayoutColors) => React.ReactNode>> = {
  title: (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.primary} />
      <rect x="5" y="9" width="5" height="1" fill={colors.accentOnPrimary} />
      <rect x="5" y="12" width="28" height="3" rx="0.5" fill={colors.textOnPrimary} />
      <rect x="5" y="17" width="18" height="1.6" rx="0.5" fill={colors.textOnPrimary} fillOpacity="0.6" />
    </>
  ),
  text: (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.background} />
      <rect x="5" y="4.5" width="22" height="2.6" rx="0.5" fill={readableColor(colors.primary, colors.background)} />
      {[11, 14, 17, 20].map((y, i) => (
        <rect key={y} x="5" y={y} width={i === 3 ? 24 : 38} height="1.3" rx="0.5" className="fill-[#9aa4b2]" />
      ))}
    </>
  ),
  bullets: (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.background} />
      <rect x="5" y="4.5" width="22" height="2.6" rx="0.5" fill={readableColor(colors.primary, colors.background)} />
      {[11, 15, 19].map((y) => (
        <g key={y}>
          <circle cx="6" cy={y + 0.65} r="0.9" fill={colors.accent} />
          <rect x="9" y={y} width="30" height="1.3" rx="0.5" className="fill-[#9aa4b2]" />
        </g>
      ))}
    </>
  ),
  'two-column': (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.background} />
      <rect x="5" y="4.5" width="22" height="2.6" rx="0.5" fill={readableColor(colors.primary, colors.background)} />
      <rect x="23.8" y="10" width="0.4" height="13" fill={colors.divider} />
      {[11, 14.5, 18].map((y) => (
        <g key={y}>
          <rect x="5" y={y} width="15" height="1.3" rx="0.5" className="fill-[#9aa4b2]" />
          <rect x="27" y={y} width="15" height="1.3" rx="0.5" className="fill-[#9aa4b2]" />
        </g>
      ))}
    </>
  ),
  section: (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.surface} />
      <rect width="1.2" height="27" fill={colors.primary} />
      <rect x="5" y="7" width="6" height="3.5" rx="0.5" fill={readableColor(colors.accent, colors.surface)} />
      <rect x="5" y="13" width="26" height="3" rx="0.5" fill={readableColor(colors.primary, colors.surface)} />
      <rect x="5" y="18.5" width="16" height="1.4" rx="0.5" className="fill-[#9aa4b2]" />
    </>
  ),
  closing: (colors) => (
    <>
      <rect width="48" height="27" rx="2" fill={colors.primary} />
      <rect x="5" y="9" width="5" height="1" fill={colors.accentOnPrimary} />
      <rect x="5" y="11.5" width="24" height="3" rx="0.5" fill={colors.textOnPrimary} />
      <rect x="5" y="17" width="14" height="1.4" rx="0.5" fill={colors.textOnPrimary} fillOpacity="0.6" />
      <rect y="25.5" width="48" height="1.5" fill={colors.accent} />
    </>
  ),
}

export function LayoutPicker({ value, colors, onChange }: { value: SlideLayout; colors: LayoutColors; onChange: (layout: SlideLayout) => void }) {
  return (
    <div role="radiogroup" aria-label="Макет слайда" className="grid grid-cols-3 gap-2">
      {layoutList.map((definition) => {
        const selected = definition.layout === value
        const Icon = definition.icon
        const schematic = SCHEMATICS[definition.layout]
        return (
          <button
            key={definition.layout}
            type="button"
            role="radio"
            aria-checked={selected}
            title={definition.description}
            onClick={() => onChange(definition.layout)}
            className={cn(
              'group relative flex flex-col items-center gap-2 border p-1.5 pb-2 text-[11.5px] transition-[border-color,color] duration-500 outline-none',
              'focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              selected ? 'border-transparent text-foreground' : 'border-border text-muted-foreground hover:border-foreground/40 hover:text-foreground',
            )}
          >
            {selected && (
              <motion.span
                layoutId="layout-picker-active"
                className="absolute inset-0 border border-foreground"
                transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
              />
            )}
            <span className="relative flex aspect-video w-full items-center justify-center overflow-hidden ring-1 ring-foreground/10">
              {schematic ? (
                <svg viewBox="0 0 48 27" className="size-full" aria-hidden>
                  {schematic(colors)}
                </svg>
              ) : (
                <Icon className="size-5" aria-hidden />
              )}
            </span>
            <span className={cn('relative leading-none', selected && 'font-medium')}>{definition.label}</span>
          </button>
        )
      })}
    </div>
  )
}
