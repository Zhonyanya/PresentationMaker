import { cn } from '@/lib/utils'

/** Знак продукта — монограмма. Не является логотипом министерства. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn('inline-flex size-8 items-center justify-center bg-foreground font-display text-[19px] leading-none text-background italic', className)}
      aria-hidden
    >
      П
    </span>
  )
}

export function BrandName({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-3">
      <BrandMark />
      <span className="flex items-baseline gap-3 leading-none">
        <span className="font-display text-[19px] tracking-[-0.01em]">Презентатор</span>
        {!compact && <span className="eyebrow hidden md:inline">Ассистент для выступлений</span>}
      </span>
    </span>
  )
}
