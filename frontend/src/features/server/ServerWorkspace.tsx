import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, LoaderCircle, LogOut, Plus, RotateCcw, TriangleAlert, X } from 'lucide-react'
import type { JobStatus, LibraryItem } from '@/api/server-api'
import type { Presentation, Slide } from '@/domain/presentation'
import type { SlideScene } from '@/layouts/scene'
import { AppHeader } from '@/components/app/AppHeader'
import { EASE_OUT_EXPO, fadeUp, lineReveal, stagger } from '@/components/app/motion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { EditorHeader } from '@/features/editor/EditorHeader'
import { ExportDialog } from '@/features/editor/ExportDialog'
import { SlideCanvas } from '@/features/editor/SlideCanvas'
import { SheetPress } from '@/features/generation/SheetPress'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { cn, plural } from '@/lib/utils'

export type Phase = JobStatus['phase']
/** Что делает задание. null — задание восстановлено после перезагрузки, вид неизвестен */
export type JobKind = 'generate' | 'revise' | null

const PHASES: { id: Phase; label: string }[] = [
  { id: 'waiting', label: 'В очереди' },
  { id: 'ml', label: 'ML-модуль готовит слайды' },
  { id: 'validation', label: 'Проверяем результат' },
  { id: 'saving', label: 'Сохраняем документ' },
  { id: 'done', label: 'Готово' },
]
export const phaseLabel = (phase: Phase) => PHASES.find((p) => p.id === phase)?.label ?? 'В работе'

function useElapsed(startedAt: number | null) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const seconds = startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/* ------------------------------------------------------------------ */
/* Аккаунт в шапке                                                     */
/* ------------------------------------------------------------------ */

export function AccountControls({ login, busy, canStartNew, onNew, onLogout }: {
  login: string
  busy: boolean
  canStartNew: boolean
  onNew?: () => void
  onLogout: () => void
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="mr-1 hidden items-center gap-2 text-[13px] text-muted-foreground xl:flex" title={login}>
        <span className="inline-flex size-6 items-center justify-center rounded-full bg-foreground/[0.07] font-display text-[13px] text-foreground italic" aria-hidden>
          {login.charAt(0).toUpperCase()}
        </span>
        <span className="max-w-[14ch] truncate">{login}</span>
      </span>
      {onNew && (
        <Button variant="ghost" size="sm" disabled={!canStartNew} onClick={onNew}>
          <Plus aria-hidden />
          <span className="max-xl:sr-only">Новая презентация</span>
        </Button>
      )}
      <Button variant="ghost" size="sm" disabled={busy} onClick={onLogout}>
        <LogOut aria-hidden />
        <span className="max-xl:sr-only">Выйти</span>
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Сообщения                                                           */
/* ------------------------------------------------------------------ */

export function Notice({ message, onDismiss, action }: { message: string; onDismiss: () => void; action?: ReactNode }) {
  return (
    <motion.div
      role="alert"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
      className="flex items-start gap-3 border-l-2 border-destructive bg-destructive-soft px-4 py-3 text-[14px] text-destructive"
    >
      <TriangleAlert className="mt-[3px] size-4 shrink-0" aria-hidden />
      <p className="flex-1 leading-snug">{message}</p>
      {action}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Скрыть сообщение"
        className="-m-1 rounded p-1 text-destructive/70 transition-colors outline-none hover:text-destructive focus-visible:ring-2 focus-visible:ring-destructive"
      >
        <X className="size-4" />
      </button>
    </motion.div>
  )
}

/** Задание идёт на сервере, но пользователь перестал ждать его на этом экране */
export function PausedJob({ phase, onResume }: { phase: Phase; onResume: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-4 border border-border bg-card px-5 py-4" aria-live="polite">
      <span className="relative flex size-2.5 shrink-0" aria-hidden>
        <span className="absolute inset-0 animate-ping rounded-full bg-brand/50" />
        <span className="relative size-2.5 rounded-full bg-brand" />
      </span>
      <div className="min-w-[16rem] flex-1">
        <p className="text-[15px]">Задание выполняется на сервере: {phaseLabel(phase)}</p>
        <p className="mt-0.5 text-[13px] text-muted-foreground">Ожидание приостановлено — результат никуда не денется. Новое задание можно начать после завершения текущего.</p>
      </div>
      <Button onClick={onResume}>Возобновить ожидание</Button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Экран ожидания задания                                              */
/* ------------------------------------------------------------------ */

function PhaseList({ phase }: { phase: Phase }) {
  const active = PHASES.findIndex((p) => p.id === phase)
  return (
    <ol className="flex flex-col border-t border-foreground" aria-label="Этапы задания">
      {PHASES.slice(0, -1).map((item, index) => {
        const done = index < active
        const current = index === active
        return (
          <li key={item.id} aria-current={current ? 'step' : undefined} className="relative flex items-baseline gap-5 border-b border-border py-3.5">
            <span className={cn('w-6 font-display text-[15px] italic tabular-nums transition-colors duration-700', current ? 'text-brand' : 'text-foreground/55')}>
              {String(index + 1).padStart(2, '0')}
            </span>
            <span className={cn('flex-1 text-[15px] transition-colors duration-700', done ? 'text-muted-foreground' : current ? 'text-foreground' : 'text-foreground/55')}>
              {item.label}
            </span>
            <span className="eyebrow !text-[10px]">{done ? 'Готово' : current ? 'В работе' : ''}</span>
            {current && (
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

export function JobWaiting({ phase, kind, startedAt, header, notice, onLeave }: {
  phase: Phase
  kind: JobKind
  startedAt: number | null
  header: ReactNode
  notice?: ReactNode
  onLeave: () => void
}) {
  const elapsed = useElapsed(startedAt)
  const [first, second] = kind === 'revise' ? ['Применяем', 'правку'] : ['Готовим', 'презентацию']
  const label = phaseLabel(phase)

  return (
    <div className="min-h-dvh">
      <AppHeader>{header}</AppHeader>
      <main className="mx-auto w-full max-w-[1280px] px-5 pt-14 pb-20 sm:px-8 lg:pt-20">
        {notice && <div className="mb-10">{notice}</div>}
        <motion.div variants={stagger(0.05, 0.08)} initial="hidden" animate="show" className="grid items-start gap-14 lg:grid-cols-12 lg:gap-10" aria-live="polite" aria-busy>
          <section className="flex flex-col lg:col-span-5">
            <motion.span variants={fadeUp} className="eyebrow">
              На сервере
            </motion.span>
            <h1 className="mt-6 font-display text-[clamp(2.4rem,5vw,4.2rem)] leading-[1] font-[380] tracking-[-0.03em]">
              <span className="block overflow-hidden pb-[0.06em]">
                <motion.span variants={lineReveal} className="block">
                  {first}
                </motion.span>
              </span>
              <span className="block overflow-hidden pb-[0.08em]">
                <motion.span variants={lineReveal} className="block italic">
                  {second}
                </motion.span>
              </span>
            </h1>
            <motion.p variants={fadeUp} className="mt-6 max-w-[44ch] text-[14px] leading-relaxed text-muted-foreground">
              Задание выполняется на сервере и не зависит от этой вкладки — её можно закрыть и вернуться позже. Редактор откроется, как только всё будет готово.
            </motion.p>

            <motion.div variants={fadeUp} className="mt-12">
              <div className="relative mb-5 h-7 overflow-hidden font-display text-[22px] leading-7 whitespace-nowrap italic" aria-hidden>
                <AnimatePresence mode="wait" initial={false}>
                  <motion.p
                    key={label}
                    initial={{ y: '110%' }}
                    animate={{ y: '0%', transition: { duration: 0.5, ease: EASE_OUT_EXPO } }}
                    exit={{ y: '-110%', transition: { duration: 0.22, ease: 'easeIn' } }}
                  >
                    {label}…
                  </motion.p>
                </AnimatePresence>
              </div>
              <PhaseList phase={phase} />
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
              <Button variant="link" onClick={onLeave} className="mb-1 text-muted-foreground hover:text-foreground">
                Вернуться к форме
              </Button>
            </div>
          </motion.div>
        </motion.div>
      </main>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Редактор серверного документа                                       */
/* ------------------------------------------------------------------ */

const THUMB_WIDTH = 168

function SlideList({ slides, scenes, selectedId, onSelect }: { slides: Slide[]; scenes: SlideScene[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <nav aria-label="Слайды" className="flex min-h-0 flex-col border-border bg-background max-lg:border-y lg:border-r">
      <div className="flex h-12 shrink-0 items-center border-b border-border px-4">
        <h2 className="eyebrow !text-foreground">
          {slides.length} {plural(slides.length, ['слайд', 'слайда', 'слайдов'])}
        </h2>
      </div>
      <ol className="scroll-thin flex min-h-0 flex-1 gap-4 overflow-auto p-3 max-lg:flex-row lg:flex-col lg:px-3 lg:py-4">
        {slides.map((slide, index) => {
          const selected = slide.id === selectedId
          return (
            <li key={slide.id} className="flex shrink-0 gap-2">
              <span className={cn('w-5 pt-0.5 text-right font-display text-[13px] italic tabular-nums transition-colors duration-500', selected ? 'text-foreground' : 'text-foreground/35')} aria-hidden>
                {index + 1}
              </span>
              <motion.button
                type="button"
                onClick={() => onSelect(slide.id)}
                aria-current={selected ? 'true' : undefined}
                aria-label={`Слайд ${index + 1}: ${slide.title.trim() || 'Без заголовка'}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: Math.min(index, 12) * 0.04, ease: EASE_OUT_EXPO }}
                className={cn(
                  'relative overflow-hidden bg-white outline-none transition-[box-shadow,transform] duration-500 ease-[cubic-bezier(0.16,1,0.3,1)]',
                  selected ? 'shadow-slide ring-[1.5px] ring-foreground ring-offset-2 ring-offset-background' : 'ring-1 ring-foreground/10 hover:-translate-y-0.5 hover:shadow-slide',
                  'focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-background',
                )}
              >
                <span className="pointer-events-none block">
                  <SlideRenderer scene={scenes[index]} scale={THUMB_WIDTH / SLIDE_PX.width} />
                </span>
              </motion.button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** Статус правки внутри панели: прежний документ остаётся доступен */
function JobStrip({ phase, waiting, onLeave, onResume }: { phase: Phase; waiting: boolean; onLeave: () => void; onResume: () => void }) {
  return (
    <div className="border border-border bg-card p-4" aria-live="polite">
      <div className="flex items-center gap-3">
        <LoaderCircle className={cn('size-4 shrink-0', waiting && 'animate-spin')} aria-hidden />
        <span className="font-display text-[17px] italic">{waiting ? `${phaseLabel(phase)}…` : 'Ожидание приостановлено'}</span>
      </div>
      {waiting && (
        <div className="mt-3 h-px overflow-hidden bg-border" aria-hidden>
          <div className="h-full w-1/3 animate-[indeterminate_2.2s_ease-in-out_infinite] bg-foreground" />
        </div>
      )}
      <p className="mt-3 text-[12.5px] leading-relaxed text-muted-foreground">Задание выполняется на сервере. Пока оно не завершится, текущий документ доступен для просмотра и экспорта.</p>
      <div className="mt-3">
        {waiting ? (
          <Button variant="link" size="sm" onClick={onLeave}>
            Вернуться к форме
          </Button>
        ) : (
          <Button size="sm" onClick={onResume}>
            Возобновить ожидание
          </Button>
        )}
      </div>
    </div>
  )
}

interface RevisionPanelProps {
  index: number
  locked: boolean
  busy: boolean
  instruction: string
  targets: string
  status?: ReactNode
  onInstruction: (value: string) => void
  onTargets: (value: string) => void
  onRevise: () => void
  onRegenerate: () => void
}

function RevisionPanel({ index, locked, busy, instruction, targets, status, onInstruction, onTargets, onRevise, onRegenerate }: RevisionPanelProps) {
  const disabled = busy || locked
  const submit = (event: FormEvent) => {
    event.preventDefault()
    onRevise()
  }
  return (
    <aside aria-label="Правка" className="scroll-thin flex min-h-0 flex-col overflow-auto border-border bg-background max-lg:border-t lg:border-l">
      <div className="flex h-12 shrink-0 items-center border-b border-border px-5">
        <h2 className="eyebrow !text-foreground">Правка командой</h2>
      </div>
      <div className="flex flex-col gap-7 p-5">
        {status}
        <p className="text-[13.5px] leading-relaxed text-muted-foreground">
          Опишите словами, что поменять, — ML-модуль перепишет слайды. Число, порядок и ID слайдов сохранятся.
        </p>
        <form className="flex flex-col gap-5" onSubmit={submit}>
          <div className="flex flex-col gap-2">
            <Label htmlFor="command">Что изменить</Label>
            <Textarea
              id="command"
              required
              rows={5}
              maxLength={10000}
              value={instruction}
              onChange={(e) => onInstruction(e.target.value)}
              disabled={disabled}
              placeholder="Например: сократи пункты до одной строки и добавь вывод"
              className="min-h-32 text-[14.5px]"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="targets">Номера слайдов через запятую (необязательно)</Label>
            <Input id="targets" inputMode="numeric" value={targets} onChange={(e) => onTargets(e.target.value)} disabled={disabled} placeholder="Например: 2, 4" className="h-10" />
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={disabled}
                onClick={() => onTargets(String(index + 1))}
                className="rounded-full border border-border px-3 py-1 text-[12.5px] transition-colors outline-none hover:border-foreground focus-visible:ring-2 focus-visible:ring-foreground disabled:opacity-50"
              >
                Только слайд {index + 1}
              </button>
              {targets.trim() && (
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onTargets('')}
                  className="rounded-full border border-border px-3 py-1 text-[12.5px] text-muted-foreground transition-colors outline-none hover:border-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-foreground disabled:opacity-50"
                >
                  Вся презентация
                </button>
              )}
            </div>
            <p className="text-[12.5px] text-muted-foreground">Без номеров правка может затронуть все слайды.</p>
          </div>
          <Button type="submit" size="lg" disabled={disabled || !instruction.trim()} className="group w-full justify-between">
            <span>Применить команду</span>
            {busy ? <LoaderCircle className="animate-spin" aria-hidden /> : <ArrowRight className="transition-transform duration-300 group-hover:translate-x-1" aria-hidden />}
          </Button>
        </form>

        <div className="flex flex-col gap-3 border-t border-border pt-6">
          <h3 className="eyebrow">Начать заново</h3>
          <p className="text-[13px] leading-relaxed text-muted-foreground">
            Полная перегенерация вернёт к форме: проверьте исходный текст и создайте новый вариант. Текущий документ останется, пока новый не будет готов.
          </p>
          <Button variant="outline" onClick={onRegenerate} disabled={locked} className="self-start">
            <RotateCcw aria-hidden />
            Полная перегенерация
          </Button>
        </div>
      </div>
    </aside>
  )
}

export function ServerEditor({ document, scenes, selected, selectedIndex, account, notice, job, exportOpen, onExportOpenChange, onSelect, onBack, ...panel }: {
  document: Presentation
  scenes: SlideScene[]
  selected: Slide
  selectedIndex: number
  account: ReactNode
  notice?: ReactNode
  /** Идёт правка или перегенерация этого документа */
  job: { phase: Phase; waiting: boolean; onLeave: () => void; onResume: () => void } | null
  exportOpen: boolean
  onExportOpenChange: (open: boolean) => void
  onSelect: (id: string) => void
  onBack: () => void
} & Omit<RevisionPanelProps, 'index' | 'locked' | 'status'>) {
  return (
    <div className="relative flex min-h-dvh flex-col bg-background lg:h-dvh lg:overflow-hidden">
      <EditorHeader title={document.title} onBack={onBack} onExport={() => onExportOpenChange(true)} extra={account} />
      {notice && <div className="shrink-0 border-b border-border px-4 py-3">{notice}</div>}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[236px_minmax(0,1fr)_340px] lg:grid-rows-[minmax(0,1fr)] xl:grid-cols-[244px_minmax(0,1fr)_360px]">
        <div className="min-h-0 max-lg:order-2 lg:contents">
          <SlideList slides={document.slides} scenes={scenes} selectedId={selected.id} onSelect={onSelect} />
        </div>
        <div className="flex min-h-0 min-w-0 flex-col max-lg:order-1 lg:contents">
          <SlideCanvas slide={selected} scene={scenes[selectedIndex]} index={selectedIndex} total={document.slides.length} activeField={null} readOnly />
        </div>
        <div className="min-h-0 max-lg:order-3 lg:contents">
          <RevisionPanel {...panel} index={selectedIndex} locked={Boolean(job)} status={job && <JobStrip {...job} />} />
        </div>
      </div>
      <ExportDialog open={exportOpen} onOpenChange={onExportOpenChange} presentation={document} scenes={scenes} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Мои презентации и удаление данных                                    */
/* ------------------------------------------------------------------ */

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
}

function LibraryRow({ item, current, busy, onOpen, onDelete }: { item: LibraryItem; current: boolean; busy: boolean; onOpen: () => void; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const title = item.title?.trim() || (item.active ? 'Готовится…' : 'Без названия')
  return (
    <li className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-border py-3.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="truncate font-display text-[17px] leading-tight">
          {title}
          {current && <span className="eyebrow ml-3 align-middle !text-[10px] !text-brand">открыта</span>}
        </p>
        <p className="mt-1 text-[12.5px] text-muted-foreground">
          {item.slide_count ? `${item.slide_count} ${plural(item.slide_count, ['слайд', 'слайда', 'слайдов'])} · ` : ''}
          {item.active ? 'задание выполняется · ' : ''}
          {formatDate(item.updated_at)}
        </p>
      </div>
      {confirming ? (
        <div className="flex items-center gap-2" role="group" aria-label={`Удалить «${title}»?`}>
          <span className="text-[13px] text-destructive">Удалить безвозвратно?</span>
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => { setConfirming(false); onDelete() }}>
            Да, удалить
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirming(false)}>
            Отмена
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <Button size="sm" variant="outline" disabled={busy} onClick={onOpen}>
            Открыть
          </Button>
          <Button size="sm" variant="ghost" disabled={busy || item.active} onClick={() => setConfirming(true)} aria-label={`Удалить «${title}»`}>
            Удалить
          </Button>
        </div>
      )}
    </li>
  )
}

function AccountDeletion({ busy, onDeleteAccount }: { busy: boolean; onDeleteAccount: (password: string) => Promise<string | null> }) {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="link-draw self-start text-[13px] text-muted-foreground outline-none hover:text-destructive focus-visible:text-destructive">
        Удалить аккаунт и все данные
      </button>
    )
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError((await onDeleteAccount(password)) ?? '')
    setPassword('')
  }
  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3 border-l-2 border-destructive bg-destructive-soft px-4 py-3">
      <p className="text-[13.5px] text-destructive">
        Аккаунт, все презентации и исходные тексты будут удалены без возможности восстановления. Введите пароль для подтверждения.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="delete-account-password" className="sr-only">
          Пароль
        </Label>
        <Input
          id="delete-account-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Пароль"
          className="h-9 max-w-[260px] bg-card"
        />
        <Button type="submit" size="sm" variant="destructive" disabled={busy || !password}>
          Удалить аккаунт
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => { setOpen(false); setPassword(''); setError('') }}>
          Отмена
        </Button>
      </div>
      {error && <p role="alert" className="text-[13px] text-destructive">{error}</p>}
    </form>
  )
}

/** Список своих презентаций с удалением — пользователь управляет своими данными */
export function Library({ items, currentId, busy, onOpen, onDelete, onDeleteAccount }: {
  items: LibraryItem[]
  currentId: string | null
  busy: boolean
  onOpen: (id: string) => void
  onDelete: (id: string) => void
  onDeleteAccount: (password: string) => Promise<string | null>
}) {
  return (
    <section aria-labelledby="library-heading" className="flex flex-col gap-4 border border-border bg-card px-5 py-4">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="library-heading" className="eyebrow !text-foreground">
          Мои презентации
        </h2>
        <span className="text-[12.5px] text-muted-foreground">Хранятся на сервере, пока вы их не удалите</span>
      </div>
      {items.length ? (
        <ul className="scroll-thin max-h-[320px] overflow-auto">
          {items.map((item) => (
            <LibraryRow
              key={item.presentation_id}
              item={item}
              current={item.presentation_id === currentId}
              busy={busy}
              onOpen={() => onOpen(item.presentation_id)}
              onDelete={() => onDelete(item.presentation_id)}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13.5px] text-muted-foreground">Пока пусто — созданные презентации появятся здесь.</p>
      )}
      <AccountDeletion busy={busy} onDeleteAccount={onDeleteAccount} />
    </section>
  )
}
