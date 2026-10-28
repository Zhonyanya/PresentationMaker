import { presentationApi } from '@/api'
import { presentationTheme } from '@/theme/presentation-theme'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/** Честные пометки: демо-режим генерации и временная тема оформления. */
export function ModeBadges({ showTheme = true }: { showTheme?: boolean }) {
  return (
    <div className="flex items-center gap-1.5">
      {presentationApi.mode === 'mock' && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="warning" tabIndex={0} className="cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ring/40">
              <span className="size-1.5 rounded-full bg-warning" aria-hidden />
              Демо-режим
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Языковая модель не подключена. Структура строится в браузере по простым правилам: заголовки, абзацы и списки исходного
            текста.
          </TooltipContent>
        </Tooltip>
      )}
      {showTheme && !presentationTheme.isOfficial && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" tabIndex={0} className="cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ring/40 max-sm:hidden">
              Временная тема
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Оформление слайдов временное и не является официальным брендбуком. Его заменят, когда будет утверждён шаблон.
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  )
}
