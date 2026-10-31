import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, ChevronDown, RotateCcw } from 'lucide-react'
import { GENERATION_STAGES, presentationApi } from '@/api'
import { useFlowStore } from '@/store/flow-store'
import { cn, formatNumber, plural } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { AppHeader } from '@/components/app/AppHeader'
import { EASE_OUT_EXPO, fadeUp, lineReveal, stagger } from '@/components/app/motion'
import { SheetPress } from './SheetPress'

function useElapsed(startedAt: number | null, running: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [running])
  if (!startedAt) return '0:00'
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function StageList() {
  const { stage, completedStages } = useFlowStore((s) => s.generation)
  return (
    <ol className="flex flex-col border-t border-foreground" aria-label="Этапы генерации">
      {GENERATION_STAGES.map((item, index) => {
        const done = completedStages.includes(item.id)
        const active = stage === item.id && !done
        return (
          <li key={item.id} aria-current={active ? 'step' : undefined} className="relative flex items-baseline gap-5 border-b border-border py-3.5">
            <span className={cn('w-6 font-display text-[15px] italic tabular-nums transition-colors duration-700', active ? 'text-brand' : 'text-foreground/55')}>
              {String(index + 1).padStart(2, '0')}
            </span>
            <span className={cn('flex-1 text-[15px] transition-colors duration-700', done ? 'text-muted-foreground' : active ? 'text-foreground' : 'text-foreground/55')}>
              {item.label}
            </span>
            <span className="eyebrow !text-[10px]">
              {done ? 'Готово' : active ? 'В работе' : ''}
              <span className="sr-only">{!done && !active ? 'Ожидает' : ''}</span>
            </span>
            {active && (
              <motion.span
                className="absolute bottom-[-1px] left-0 h-px bg-foreground"
                initial={{ width: '0%' }}
                animate={{ width: '100%' }}
                transition={{ duration: 1.6, ease: EASE_OUT_EXPO }}
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}

function ErrorState() {
  const error = useFlowStore((s) => s.generation.error)
  const generate = useFlowStore((s) => s.generate)
  const backToCreate = useFlowStore((s) => s.backToCreate)
  const [showDetails, setShowDetails] = useState(false)
  if (!error) return null
  return (
    <motion.section variants={stagger(0.05, 0.08)} initial="hidden" animate="show" className="mx-auto flex w-full max-w-[640px] flex-col" role="alert">
      <motion.span variants={fadeUp} className="eyebrow !text-destructive">
        Ошибка генерации
      </motion.span>
      <h1 className="mt-5 font-display text-[clamp(2.2rem,4.5vw,3.4rem)] leading-[1.02] font-[380] tracking-[-0.025em]">
        <span className="block overflow-hidden pb-[0.06em]">
          <motion.span variants={lineReveal} className="block">
            Не удалось создать
          </motion.span>
        </span>
        <span className="block overflow-hidden pb-[0.08em]">
          <motion.span variants={lineReveal} className="block italic">
            презентацию
          </motion.span>
        </span>
      </h1>
      <motion.p variants={fadeUp} className="mt-6 max-w-[48ch] text-[16px] leading-relaxed text-muted-foreground">
        {error.message} Исходный текст сохранён — ничего вводить заново не нужно.
      </motion.p>
      <motion.div variants={fadeUp} className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-4 border-t border-border pt-6">
        {error.retryable && (
          <Button size="lg" onClick={() => void generate()} autoFocus>
            <RotateCcw />
            Повторить
          </Button>
        )}
        <Button variant="link" onClick={backToCreate}>
          <ArrowLeft />
          Вернуться к тексту
        </Button>
      </motion.div>
      <motion.div variants={fadeUp} className="mt-10">
        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          aria-expanded={showDetails}
          className="eyebrow inline-flex items-center gap-1.5 outline-none hover:!text-foreground focus-visible:ring-2 focus-visible:ring-foreground"
        >
          <ChevronDown className={cn('size-3.5 transition-transform duration-500', showDetails && 'rotate-180')} />
          Подробности для разработчиков
        </button>
        <AnimatePresence>
          {showDetails && (
            <motion.pre
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.5, ease: EASE_OUT_EXPO }}
              className="scroll-thin mt-3 max-h-48 overflow-auto bg-foreground p-4 font-mono text-[11.5px] leading-relaxed text-background/80"
            >
              {JSON.stringify({ code: error.code, status: error.status, details: error.details ?? null }, null, 2)}
            </motion.pre>
          )}
        </AnimatePresence>
      </motion.div>
    </motion.section>
  )
}

export function GenerationView() {
  const generation = useFlowStore((s) => s.generation)
  const draft = useFlowStore((s) => s.draft)
  const cancel = useFlowStore((s) => s.cancel)
  const running = generation.status === 'running'
  const elapsed = useElapsed(generation.startedAt, running)
  const reportsStages = presentationApi.reportsStages
  const currentLabel = GENERATION_STAGES.find((s) => s.id === generation.stage)?.label ?? 'Начинаем'

  return (
    <div className="min-h-dvh">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1280px] px-5 pt-14 pb-20 sm:px-8 lg:pt-20">
        {generation.status === 'error' ? (
          <ErrorState />
        ) : (
          <motion.div
            variants={stagger(0.05, 0.08)}
            initial="hidden"
            animate="show"
            className="grid items-start gap-14 lg:grid-cols-12 lg:gap-10"
            aria-live="polite"
            aria-busy={running}
          >
            <section className="flex flex-col lg:col-span-5">
              <motion.div variants={fadeUp} className="flex flex-wrap items-center gap-3">
                <span className="eyebrow">В работе</span>
                {reportsStages && presentationApi.mode === 'mock' && <Badge variant="warning">Демо: этапы имитируются</Badge>}
              </motion.div>

              <h1 className="mt-6 font-display text-[clamp(2.4rem,5vw,4.2rem)] leading-[1] font-[380] tracking-[-0.03em]">
                <span className="block overflow-hidden pb-[0.06em]">
                  <motion.span variants={lineReveal} className="block">
                    Готовим
                  </motion.span>
                </span>
                <span className="block overflow-hidden pb-[0.08em]">
                  <motion.span variants={lineReveal} className="block italic">
                    презентацию
                  </motion.span>
                </span>
              </h1>

              <motion.p variants={fadeUp} className="mt-6 text-[14px] text-muted-foreground">
                {draft.title.trim() ? `«${draft.title.trim()}» · ` : ''}≈ {draft.slideCount} {plural(draft.slideCount, ['слайд', 'слайда', 'слайдов'])} ·{' '}
                {formatNumber(draft.text.length)} знаков
              </motion.p>

              <motion.div variants={fadeUp} className="mt-12">
                {reportsStages ? (
                  <>
                    <div className="relative mb-5 h-7 overflow-hidden font-display text-[22px] leading-7 whitespace-nowrap italic" aria-hidden>
                      <AnimatePresence mode="wait" initial={false}>
                        <motion.p
                          key={currentLabel}
                          initial={{ y: '110%' }}
                          animate={{ y: '0%', transition: { duration: 0.5, ease: EASE_OUT_EXPO } }}
                          exit={{ y: '-110%', transition: { duration: 0.22, ease: 'easeIn' } }}
                        >
                          {currentLabel}…
                        </motion.p>
                      </AnimatePresence>
                    </div>
                    <StageList />
                  </>
                ) : (
                  <div className="flex flex-col gap-4 border-t border-foreground pt-5">
                    <div className="h-px overflow-hidden bg-border" role="progressbar" aria-label="Генерация презентации" aria-valuetext="Выполняется">
                      <div className="h-full w-1/3 animate-[indeterminate_2.2s_ease-in-out_infinite] bg-foreground" />
                    </div>
                    <p className="font-display text-[20px] italic">Языковая модель готовит структуру и текст слайдов</p>
                    <p className="text-[13.5px] leading-relaxed text-muted-foreground">
                      Обычно это занимает несколько минут. Можно заниматься другими делами — редактор откроется, как только всё будет готово.
                    </p>
                  </div>
                )}
              </motion.div>

            </section>

            <motion.div variants={fadeUp} className="lg:col-span-7 lg:pt-6">
              <SheetPress />
              <div className="mx-auto mt-2 flex max-w-[640px] items-end justify-between gap-6 border-t border-border pt-4">
                <div className="flex items-baseline gap-4">
                  <span className="font-display text-[44px] leading-none font-[360] tabular-nums italic" aria-label={`Прошло ${elapsed}`}>
                    {elapsed}
                  </span>
                  <span className="eyebrow">прошло</span>
                </div>
                <Button variant="link" onClick={cancel} className="mb-1 text-muted-foreground hover:text-foreground">
                  Отменить
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </main>
    </div>
  )
}
