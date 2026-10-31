import { useEffect, useState } from 'react'
import { env } from '@/config/env'
import { presentationTheme } from '@/theme/presentation-theme'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

let adapterRequest: Promise<string | null> | null = null

/** Какой ML подключён к серверу — один запрос на всё приложение. */
function fetchMlAdapter(): Promise<string | null> {
  adapterRequest ??= fetch(`${env.apiBaseUrl}/api/v1/health/ready`, { credentials: 'include', cache: 'no-store' })
    .then((response) => (response.ok ? response.json() : null))
    .then((body: { ml_adapter?: unknown } | null) => (typeof body?.ml_adapter === 'string' ? body.ml_adapter : null))
    .catch(() => null)
  return adapterRequest
}

/** Сервер работает на тестовой заглушке вместо настоящего ML-модуля. */
export function useMlStub(): boolean {
  const [stub, setStub] = useState(false)
  useEffect(() => {
    if (env.apiMode !== 'http') return
    let alive = true
    void fetchMlAdapter().then((adapter) => {
      if (alive) setStub(adapter === 'fixture')
    })
    return () => {
      alive = false
    }
  }, [])
  return stub
}

const badgeTrigger = 'cursor-help outline-none focus-visible:ring-2 focus-visible:ring-ring/40'

/** Честные пометки: демо-режим или заглушка ML и временная тема оформления. */
export function ModeBadges({ showTheme = true }: { showTheme?: boolean }) {
  const stub = useMlStub()
  return (
    <div className="flex items-center gap-1.5">
      {env.apiMode === 'mock' && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="warning" tabIndex={0} className={badgeTrigger}>
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
      {stub && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="warning" tabIndex={0} className={badgeTrigger}>
              <span className="size-1.5 rounded-full bg-warning" aria-hidden />
              Заглушка ML
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Сервер подключён к тестовой заглушке вместо ML-модуля: генерация возвращает одну и ту же демонстрационную презентацию,
            а правка меняет только заметки докладчика.
          </TooltipContent>
        </Tooltip>
      )}
      {showTheme && !presentationTheme.isOfficial && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="outline" tabIndex={0} className={`${badgeTrigger} max-sm:hidden`}>
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
