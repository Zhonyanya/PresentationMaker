import { Component, type ErrorInfo, type ReactNode } from 'react'
import { BrandMark } from './BrandMark'
import { safeStorage } from '@/lib/storage'

/** Ключи, которые приложение хранит в браузере: черновики демо-режима и ссылки на документы */
const STORED_PREFIXES = ['ai-presentations:', 'pm:current:']

function resetStoredDrafts() {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (STORED_PREFIXES.some((prefix) => key.startsWith(prefix))) safeStorage.removeItem(key)
    }
  } catch {
    /* хранилище недоступно — сбрасывать нечего */
  }
}

/**
 * Последний рубеж: неожиданная ошибка отрисовки показывает понятный экран
 * с выходом, а не пустую страницу, которая повторяется при каждом обновлении.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[app] Ошибка отрисовки', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main role="alert" className="flex min-h-dvh items-center justify-center bg-background px-5">
        <div className="flex max-w-[460px] flex-col items-start">
          <BrandMark className="size-10 text-[24px]" />
          <h1 className="mt-8 font-display text-[clamp(2.2rem,5vw,3rem)] leading-none font-[340] tracking-[-0.03em]">Что-то пошло не так</h1>
          <p className="mt-5 text-[15px] leading-relaxed text-muted-foreground">
            Страница не смогла отобразиться. Обычно помогает обновление. Если ошибка повторяется, сбросьте черновик, сохранённый в
            этом браузере: документы на сервере не пострадают.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="h-10 rounded-[3px] bg-foreground px-5 text-[14px] font-medium text-background outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2"
            >
              Обновить страницу
            </button>
            <button
              type="button"
              onClick={() => {
                resetStoredDrafts()
                window.location.reload()
              }}
              className="h-10 rounded-[3px] border border-foreground/25 px-5 text-[14px] font-medium outline-none hover:border-foreground focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2"
            >
              Сбросить черновик
            </button>
          </div>
        </div>
      </main>
    )
  }
}
