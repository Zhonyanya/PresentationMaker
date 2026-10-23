import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { pageTransition } from '@/components/app/motion'
import { Splash, shouldShowSplash } from '@/features/intro/Splash'
import { CreatePage } from '@/features/create/CreatePage'
import { GenerationView } from '@/features/generation/GenerationView'
import { EditorPage } from '@/features/editor/EditorPage'
import { useFlowStore } from '@/store/flow-store'
import { useEditorStore } from '@/store/editor-store'

const TITLES = {
  create: 'Новая презентация',
  generating: 'Готовим презентацию',
  editor: 'Редактор',
} as const

export default function App() {
  const view = useFlowStore((s) => s.view)
  const hasPresentation = useEditorStore((s) => Boolean(s.presentation))
  // Редактор без презентации (например, черновик удалён) — возвращаемся к созданию
  const current = view === 'editor' && !hasPresentation ? 'create' : view

  // Заставка при первом открытии: сайт монтируется, когда занавес начинает подниматься,
  // чтобы его собственные анимации появления шли вместе с открытием
  const [splash, setSplash] = useState(shouldShowSplash)
  const [revealed, setRevealed] = useState(() => !splash)
  const reveal = useCallback(() => setRevealed(true), [])
  const finishSplash = useCallback(() => setSplash(false), [])

  useEffect(() => {
    document.title = `${TITLES[current]} — Презентатор`
  }, [current])

  return (
    // reducedMotion="user" — при системной настройке «Уменьшить движение» анимации отключаются
    <MotionConfig reducedMotion="user">
      <TooltipProvider>
        <div className="relative isolate min-h-dvh">
          {/* Прокрутка наверх — когда старый экран уже ушёл, иначе новый откроется на середине */}
          <AnimatePresence mode="wait" initial={false} onExitComplete={() => window.scrollTo({ top: 0 })}>
            {revealed && (
              <motion.div key={current} variants={pageTransition} initial="initial" animate="animate" exit="exit">
                {current === 'create' && <CreatePage />}
                {current === 'generating' && <GenerationView />}
                {current === 'editor' && <EditorPage />}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        {splash && <Splash onReveal={reveal} onDone={finishSplash} />}
        <Toaster />
      </TooltipProvider>
    </MotionConfig>
  )
}
