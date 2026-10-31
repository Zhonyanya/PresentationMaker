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

/**
 * @param collapse В шапке есть другие элементы (аккаунт): на узком экране остаётся
 *   только монограмма, подзаголовок — только на широком.
 */
export function BrandName({ compact = false, collapse = false }: { compact?: boolean; collapse?: boolean }) {
  return (
    <span className="flex items-center gap-3">
      <BrandMark />
      <span className="flex items-baseline gap-3 leading-none">
        <span className={cn('font-display text-[19px] tracking-[-0.01em]', collapse && 'max-sm:sr-only')}>Презентатор</span>
        {!compact && <span className={cn('eyebrow hidden', collapse ? 'xl:inline' : 'md:inline')}>Ассистент для выступлений</span>}
      </span>
    </span>
  )
}
