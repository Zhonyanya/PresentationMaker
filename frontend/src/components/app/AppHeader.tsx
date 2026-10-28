import type { ReactNode } from 'react'
import { BrandName } from './BrandMark'
import { ModeBadges } from './ModeBadges'

export function AppHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="sticky z-30 border-b border-border bg-background" style={{ top: 'env(safe-area-inset-top, 0px)' }}>
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center justify-between gap-4 px-5 sm:px-8">
        <BrandName />
        <div className="flex items-center gap-4">
          {children}
          <ModeBadges />
        </div>
      </div>
    </header>
  )
}
