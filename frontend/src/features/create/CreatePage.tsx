import { useId, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { motion, useReducedMotion, useScroll, useTransform } from 'motion/react'
import { ArrowRight } from 'lucide-react'
import { toast } from 'sonner'
import { generateRequestSchema, LIMITS, type GenerateRequest } from '@/domain/presentation'
import { demoExamples, type DemoExample } from '@/data/demo-examples'
import { useFlowStore } from '@/store/flow-store'
import { useEditorStore } from '@/store/editor-store'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { AppHeader } from '@/components/app/AppHeader'
import { EASE_OUT_EXPO, fadeUp, lineReveal, stagger } from '@/components/app/motion'
import { SourceTextField } from './SourceTextField'
import { SlideCountField } from './SlideCountField'
import { ExampleList } from './ExampleList'
import { DraftBanner } from './DraftBanner'
import { HeroShowcase } from './HeroShowcase'
import { ValueTicker } from './ValueTicker'
import { StoryScroll } from './StoryScroll'
import { SiteCursor } from '@/components/app/Cursor'
import { JumpCurtain, useJumpCurtain } from '@/components/app/JumpCurtain'
import { Magnetic } from '@/components/app/Magnetic'
import { jumpTo, smoothScrollTo, useSmoothScroll } from '@/components/app/smooth-scroll'

const FACTS = [
  { value: '6', label: 'типовых макетов: титульный, текст, список, две колонки, раздел, финал' },
  { value: 'PPTX', label: 'настоящий файл PowerPoint — каждое слово остаётся редактируемым' },
  { value: '16:9', label: 'единая сетка, шрифты и цвета на каждом слайде' },
]

const STEPS = [
  { title: 'Вставьте материал', text: 'Текст доклада, тезисы или план выступления.' },
  { title: 'Проверьте слайды', text: 'Поправьте формулировки, порядок и макеты.' },
  { title: 'Скачайте файл', text: 'PPTX открывается в PowerPoint как обычно.' },
]

/** В серверном режиме документ правится командами, а не вручную */
const SERVER_STEPS = STEPS.map((step, i) => (i === 1 ? { ...step, text: 'Уточните формулировки командами в редакторе.' } : step))

interface FieldErrors {
  text?: string
  title?: string
}

function SectionLabel({ number, title, aside }: { number: string; title: string; aside?: string }) {
  return (
    <div className="relative flex items-baseline justify-between gap-4 pt-4">
      {/* Линия рубрики прорисовывается, когда раздел появляется на экране */}
      <motion.span
        aria-hidden
        className="absolute inset-x-0 top-0 h-px origin-left bg-foreground"
        initial={{ scaleX: 0 }}
        whileInView={{ scaleX: 1 }}
        viewport={{ once: true, margin: '-40px' }}
        transition={{ duration: 1.3, ease: EASE_OUT_EXPO }}
      />
      <div className="flex items-baseline gap-4">
        <span className="font-display text-[15px] italic text-brand">{number}</span>
        <h2 className="eyebrow !text-foreground">{title}</h2>
      </div>
      {aside && <span className="eyebrow hidden sm:inline">{aside}</span>}
    </div>
  )
}

export function CreatePage({ onGenerate, onOpenCurrent, onDiscardCurrent, serverMode = false, headerSlot, notice, startAtWorkspace = false }: {
  onGenerate?: (request: GenerateRequest) => void
  onOpenCurrent?: () => void
  /** Серверный режим: забыть текущую презентацию, чтобы следующая генерация создала новую */
  onDiscardCurrent?: () => void
  serverMode?: boolean
  /** Дополнительные элементы шапки — например, аккаунт в серверном режиме */
  headerSlot?: ReactNode
  /** Сообщение над рабочей областью: ошибка или статус задания */
  notice?: ReactNode
  /** Открыть сразу на рабочей области, а не на обложке — при возврате из редактора или ожидания */
  startAtWorkspace?: boolean
} = {}) {
  const titleId = useId()
  const textId = useId()
  const workspaceRef = useRef<HTMLDivElement>(null)
  const examplesRef = useRef<HTMLDivElement>(null)
  const draft = useFlowStore((s) => s.draft)
  const setDraft = useFlowStore((s) => s.setDraft)
  const generate = useFlowStore((s) => s.generate)
  const openEditor = useFlowStore((s) => s.openEditor)
  const savedPresentation = useEditorStore((s) => s.presentation)
  const savedAt = useEditorStore((s) => s.savedAt)
  const closeEditor = useEditorStore((s) => s.close)
  const [errors, setErrors] = useState<FieldErrors>({})

  // Параллакс обложки: заголовок уходит вверх быстрее колоды — появляется глубина
  const reduceMotion = useReducedMotion()
  const { scrollY } = useScroll()
  const headlineY = useTransform(scrollY, [0, 700], [0, reduceMotion ? 0 : -90])
  const headlineOpacity = useTransform(scrollY, [0, 520], [1, reduceMotion ? 1 : 0.35])
  const deckY = useTransform(scrollY, [0, 700], [0, reduceMotion ? 0 : 50])
  useSmoothScroll(!reduceMotion)
  // Только при первом показе: дальше пользователь прокручивает сам
  useLayoutEffect(() => { if (startAtWorkspace) jumpTo(workspaceRef.current) }, [])

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    const result = generateRequestSchema.safeParse({
      text: draft.text,
      title: draft.title.trim() || undefined,
      slideCount: draft.slideCount,
    })
    if (!result.success) {
      const next: FieldErrors = {}
      for (const issue of result.error.issues) {
        const key = issue.path[0] as keyof FieldErrors
        if ((key === 'text' || key === 'title') && !next[key]) {
          next[key] = draft.text.trim() === '' && key === 'text' ? 'Вставьте текст доклада или план выступления' : issue.message
        }
      }
      setErrors(next)
      document.getElementById(next.text ? textId : titleId)?.focus()
      return
    }
    setErrors({})
    if (onGenerate) onGenerate(result.data)
    else void generate()
  }

  const curtain = useJumpCurtain()
  const focusText = () => document.getElementById(textId)?.focus({ preventScroll: true })

  // Далеко (через сцену «Как это работает») — переход занавесом, чтобы сцена
  // не проматывалась за долю секунды. Рядом — обычная плавная прокрутка.
  const goToWorkspace = () => {
    const target = workspaceRef.current
    if (!target) return
    const distance = Math.abs(target.getBoundingClientRect().top)
    if (distance > window.innerHeight * 1.2) {
      curtain.run('Новая презентация', () => jumpTo(target), focusText)
    } else {
      smoothScrollTo(target)
      window.setTimeout(focusText, 900)
    }
  }

  const pickExample = (example: DemoExample) => {
    setDraft({ text: example.text, title: example.title, slideCount: example.slideCount })
    setErrors({})
    toast.success('Пример загружен', { description: example.label })
    goToWorkspace()
  }

  const showExamples = () => {
    smoothScrollTo(examplesRef.current, -160)
    examplesRef.current?.querySelector('button')?.focus({ preventScroll: true })
  }

  return (
    <div className="min-h-dvh">
      <SiteCursor />
      <JumpCurtain phase={curtain.phase} label={curtain.label} />
      <AppHeader>{headerSlot}</AppHeader>

      {/* ——— Обложка ——— */}
      <section className="mx-auto w-full max-w-[1280px] px-5 pt-10 sm:px-8 lg:pt-14">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8 }} className="flex items-center justify-between border-b border-border pb-4">
          <span className="eyebrow">Подготовка выступлений</span>
          <span className="eyebrow hidden sm:inline">Прототип · {new Date().getFullYear()}</span>
        </motion.div>

        <div className="grid gap-12 pt-12 pb-16 lg:grid-cols-12 lg:gap-10 lg:pt-16 lg:pb-24">
          <motion.div
            variants={stagger(0.1, 0.08)}
            initial="hidden"
            animate="show"
            style={{ y: headlineY }}
            className="flex min-w-0 flex-col lg:col-span-6"
          >
            <motion.h1 style={{ opacity: headlineOpacity }} className="font-display text-[clamp(2.6rem,5.2vw,5rem)] leading-[1] font-[380] tracking-[-0.03em] max-[400px]:text-[2.2rem]">
              <span className="block overflow-hidden pb-[0.06em]">
                <motion.span variants={lineReveal} className="block whitespace-nowrap">
                  Из доклада&nbsp;—
                </motion.span>
              </span>
              <span className="block overflow-hidden pb-[0.08em]">
                <motion.span variants={lineReveal} className="block whitespace-nowrap">
                  в&nbsp;<em className="font-[340] italic">презентацию</em>
                </motion.span>
              </span>
            </motion.h1>

            <motion.p variants={fadeUp} className="mt-8 max-w-[42ch] text-[17px] leading-[1.65] text-muted-foreground">
              Вставьте текст выступления — ассистент выстроит структуру и разложит её по слайдам в едином оформлении. Остаётся
              проверить формулировки и скачать файл.
            </motion.p>

            <motion.div variants={fadeUp} className="mt-10 flex flex-wrap items-center gap-x-8 gap-y-4">
              <Magnetic>
                <Button size="xl" className="group" onClick={goToWorkspace}>
                  Начать работу
                  <ArrowRight className="transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-1" />
                </Button>
              </Magnetic>
              <button type="button" onClick={() => pickExample(demoExamples[0])} className="link-draw pb-0.5 text-[14.5px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-4 focus-visible:ring-offset-background">
                Открыть пример доклада
              </button>
            </motion.div>
          </motion.div>

          <motion.div style={{ y: deckY }} className="min-w-0 lg:col-span-6 lg:pt-12">
            <HeroShowcase />
          </motion.div>
        </div>

        <ValueTicker />

        <motion.dl
          variants={stagger(0.2, 0.1)}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
          className="grid border-t border-border sm:grid-cols-3"
        >
          {FACTS.map(({ value, label }, i) => (
            <motion.div
              key={value}
              variants={fadeUp}
              className={`flex flex-col gap-3 py-7 sm:px-8 ${i === 0 ? 'sm:pl-0' : 'border-t border-border sm:border-t-0 sm:border-l'}`}
            >
              <dt className="overflow-hidden pb-[0.08em] font-display text-[44px] leading-none font-[380] tracking-[-0.02em]">
                <motion.span variants={lineReveal} className="block">
                  {value}
                </motion.span>
              </dt>
              <dd className="max-w-[30ch] text-[13.5px] leading-relaxed text-muted-foreground">{label}</dd>
            </motion.div>
          ))}
        </motion.dl>
      </section>

      {/* ——— Как это работает: сцена, управляемая прокруткой ——— */}
      <StoryScroll />

      {/* ——— Рабочая область ——— */}
      <main ref={workspaceRef} className="mx-auto w-full max-w-[1280px] scroll-mt-20 px-5 pt-16 pb-24 sm:px-8 lg:pt-24">
        {notice && <div className="mb-12 flex flex-col gap-4">{notice}</div>}
        {savedPresentation && (
          <div className="mb-12">
            <DraftBanner
              title={savedPresentation.title}
              slideCount={savedPresentation.slides.length}
              savedAt={savedAt}
              onContinue={onOpenCurrent ?? openEditor}
              serverMode={serverMode}
              onDiscard={() => {
                if (serverMode) {
                  // Иначе «Создать презентацию» перегенерировала бы скрытый документ
                  onDiscardCurrent?.()
                  return
                }
                const backup = savedPresentation
                closeEditor()
                toast('Черновик удалён', {
                  duration: 8000,
                  action: { label: 'Вернуть', onClick: () => useEditorStore.getState().load(backup) },
                })
              }}
            />
          </div>
        )}

        <motion.div
          variants={stagger(0.05, 0.1)}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: '-60px' }}
          className="grid items-start gap-x-10 gap-y-14 lg:grid-cols-12"
        >
          <motion.div variants={fadeUp} className="flex min-w-0 flex-col gap-6 lg:col-span-8">
            <SectionLabel number="01" title="Исходный материал" aside="Обязательно" />
            <form onSubmit={submit} noValidate className="flex flex-col gap-8" aria-label="Исходные данные презентации">
              <div className="flex flex-col gap-2">
                <Label htmlFor={titleId} className="eyebrow">
                  Название — необязательно
                </Label>
                <input
                  id={titleId}
                  value={draft.title}
                  maxLength={LIMITS.titleMax}
                  onChange={(e) => setDraft({ title: e.target.value })}
                  placeholder="Итоги учебного года"
                  aria-invalid={Boolean(errors.title)}
                  aria-describedby={`${titleId}-hint`}
                  autoComplete="off"
                  className="w-full border-0 border-b border-input bg-transparent pt-1 pb-3 font-display text-[clamp(1.6rem,2.6vw,2.1rem)] leading-tight font-[380] tracking-[-0.015em] outline-none transition-colors duration-300 placeholder:text-foreground/25 hover:border-[#a9a191] focus-visible:border-foreground aria-invalid:border-destructive"
                />
                <p id={`${titleId}-hint`} className={errors.title ? 'text-xs font-medium text-destructive' : 'text-xs text-muted-foreground'}>
                  {errors.title ?? 'Если оставить пустым, название возьмём из текста.'}
                </p>
              </div>

              <SourceTextField
                id={textId}
                value={draft.text}
                onChange={(text) => {
                  setDraft({ text })
                  if (errors.text) setErrors((e) => ({ ...e, text: undefined }))
                }}
                error={errors.text}
                onSubmitShortcut={() => submit()}
                onShowExamples={showExamples}
              />

              <div className="flex flex-col-reverse gap-4 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
                <p className="hidden text-xs text-muted-foreground sm:block">
                  <kbd className="font-sans font-medium text-foreground">Ctrl + Enter</kbd> — создать, не отрывая рук от клавиатуры
                </p>
                <Magnetic className="w-full sm:w-auto">
                  <Button type="submit" size="xl" className="group w-full sm:w-auto">
                    Создать презентацию
                    <ArrowRight className="transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-1" />
                  </Button>
                </Magnetic>
              </div>
            </form>
          </motion.div>

          <aside className="flex min-w-0 flex-col gap-14 lg:col-span-4" aria-label="Параметры и примеры">
            <motion.section variants={fadeUp} className="flex flex-col gap-6" aria-labelledby="params-heading">
              <SectionLabel number="02" title="Объём" />
              <h2 id="params-heading" className="sr-only">
                Объём
              </h2>
              <SlideCountField value={draft.slideCount} onChange={(slideCount) => setDraft({ slideCount })} />
            </motion.section>

            <motion.section variants={fadeUp} ref={examplesRef} className="flex flex-col gap-4" aria-labelledby="examples-heading">
              <SectionLabel number="03" title="Примеры" />
              <h2 id="examples-heading" className="sr-only">
                Примеры
              </h2>
              <p className="text-[13px] leading-relaxed text-muted-foreground">Вымышленные тексты для проверки — заменят содержимое поля.</p>
              <ExampleList onPick={pickExample} />
            </motion.section>

            <motion.section variants={fadeUp} className="flex flex-col gap-5" aria-labelledby="how-heading">
              <SectionLabel number="04" title="Порядок работы" />
              <h2 id="how-heading" className="sr-only">
                Порядок работы
              </h2>
              <ol className="flex flex-col">
                {(serverMode ? SERVER_STEPS : STEPS).map(({ title, text }, i) => (
                  <motion.li
                    key={title}
                    initial={{ opacity: 0, x: -12 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.9, delay: 0.15 + i * 0.12, ease: EASE_OUT_EXPO }}
                    className="flex gap-5 border-b border-border py-4 first:pt-0 last:border-b-0"
                  >
                    <span className="font-display text-[26px] leading-none font-[380] text-foreground/35 tabular-nums">{i + 1}</span>
                    <span className="flex flex-col gap-1">
                      <span className="text-[14px] font-medium">{title}</span>
                      <span className="text-[13px] leading-relaxed text-muted-foreground">{text}</span>
                    </span>
                  </motion.li>
                ))}
              </ol>
            </motion.section>
          </aside>
        </motion.div>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-[1280px] flex-wrap items-center justify-between gap-3 px-5 py-6 sm:px-8">
          <span className="font-display text-[15px] italic text-muted-foreground">Презентатор</span>
          <span className="eyebrow">Оформление слайдов — временная тема до утверждения брендбука</span>
        </div>
      </footer>
    </div>
  )
}
