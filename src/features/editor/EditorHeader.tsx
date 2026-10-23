import { ArrowLeft, Check, Download } from 'lucide-react'
import { BrandMark } from '@/components/app/BrandMark'
import { ModeBadges } from '@/components/app/ModeBadges'
import { Button } from '@/components/ui/button'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { LIMITS } from '@/domain/presentation'

interface EditorHeaderProps {
  title: string
  onTitleChange: (title: string) => void
  onBack: () => void
  onExport: () => void
}

export function EditorHeader({ title, onTitleChange, onBack, onExport }: EditorHeaderProps) {
  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background px-2 sm:gap-3 sm:px-4" style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}>
      <SimpleTooltip label="К исходному тексту — презентация сохранится">
        <Button variant="ghost" size="sm" onClick={onBack} aria-label="К исходному тексту" className="gap-2 px-2">
          <ArrowLeft />
          <BrandMark className="size-7 max-sm:hidden" />
        </Button>
      </SimpleTooltip>
      <span className="h-5 w-px bg-border max-sm:hidden" aria-hidden />

      <div className="min-w-0 flex-1">
        <label htmlFor="presentation-title" className="sr-only">
          Название презентации
        </label>
        <input
          id="presentation-title"
          value={title}
          maxLength={LIMITS.titleMax}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder="Без названия"
          className="h-9 w-full max-w-[520px] truncate rounded-lg border border-transparent bg-transparent px-2.5 font-display text-[18px] font-[400] tracking-[-0.01em] outline-none transition-[border-color,background-color] hover:border-border focus-visible:border-ring focus-visible:bg-card focus-visible:ring-[3px] focus-visible:ring-ring/20"
        />
      </div>

      <div className="flex shrink-0 items-center gap-3">
        <span className="hidden items-center gap-1.5 text-xs text-muted-foreground xl:flex" aria-live="polite">
          <Check className="size-3.5 text-success" aria-hidden />
          Сохранено в браузере
        </span>
        <div className="max-md:hidden">
          <ModeBadges />
        </div>
        <Button onClick={onExport} className="max-sm:px-3">
          <Download />
          <span className="max-sm:sr-only">Скачать PPTX</span>
        </Button>
      </div>
    </header>
  )
}
