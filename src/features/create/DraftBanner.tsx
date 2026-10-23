import { History } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/utils'

interface DraftBannerProps {
  title: string
  slideCount: number
  savedAt: string | null
  onContinue: () => void
  onDiscard: () => void
}

function formatSavedAt(savedAt: string | null): string {
  if (!savedAt) return ''
  const date = new Date(savedAt)
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay
    ? `сегодня в ${date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`
    : date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

export function DraftBanner({ title, slideCount, savedAt, onContinue, onDiscard }: DraftBannerProps) {
  return (
    <div className="flex flex-col gap-4 border border-foreground/80 bg-card px-5 py-4 animate-in fade-in-0 duration-700 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <History className="size-5 shrink-0 text-brand" aria-hidden />
        <div className="min-w-0">
          <p className="truncate font-display text-[17px] leading-tight">Незавершённая презентация «{title || 'Без названия'}»</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {slideCount} {plural(slideCount, ['слайд', 'слайда', 'слайдов'])}
            {savedAt && ` · сохранено ${formatSavedAt(savedAt)}`}
          </p>
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button variant="ghost" size="sm" onClick={onDiscard}>
          Удалить черновик
        </Button>
        <Button size="sm" onClick={onContinue}>
          Продолжить редактирование
        </Button>
      </div>
    </div>
  )
}
