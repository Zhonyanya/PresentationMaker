import { useId, useMemo, useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, Eye, EyeOff, LoaderCircle, LockKeyhole } from 'lucide-react'
import { BrandMark, BrandName } from '@/components/app/BrandMark'
import { ModeBadges } from '@/components/app/ModeBadges'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getShowcase } from '@/features/create/showcase'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { useElementSize } from '@/hooks/useElementSize'
import { cn } from '@/lib/utils'

export type AuthKind = 'login' | 'register'

const PASSWORD_MIN = 15
const PASSWORD_MAX = 128

const COPY = {
  login: {
    tab: 'Вход',
    title: 'С возвращением.',
    lead: 'Войдите, чтобы продолжить работу над презентациями.',
    submit: 'Войти',
    pending: 'Входим…',
    switchPrompt: 'Нет аккаунта?',
    switchAction: 'Создать',
  },
  register: {
    tab: 'Регистрация',
    title: 'Новый аккаунт.',
    lead: 'Нужны только логин и пароль. Почта и телефон не требуются.',
    submit: 'Создать аккаунт',
    pending: 'Создаём аккаунт…',
    switchPrompt: 'Уже есть аккаунт?',
    switchAction: 'Войти',
  },
} as const

/** Веер настоящих слайдов демо-презентации на чернильной панели */
const FAN = [
  { x: '-16%', y: '10%', rotate: -8 },
  { x: '14%', y: '4%', rotate: 5 },
  { x: '0%', y: '-6%', rotate: -1.5 },
]

function SlideFan() {
  const [ref, size] = useElementSize<HTMLDivElement>()
  const scenes = useMemo(() => {
    const { gallery } = getShowcase()
    return [gallery[2], gallery[1], gallery[0]].filter(Boolean)
  }, [])
  const width = Math.min(size.width * 0.72, 440)

  return (
    <div ref={ref} className="relative h-full w-full" aria-hidden>
      {width > 0 &&
        scenes.map((scene, i) => (
          <motion.div
            key={i}
            className="absolute top-1/2 left-1/2 shadow-[0_2px_2px_rgb(0_0_0/0.25),0_40px_70px_-30px_rgb(0_0_0/0.8)]"
            style={{ width, height: (width * 9) / 16, marginLeft: -width / 2, marginTop: (-width * 9) / 32 }}
            initial={{ opacity: 0, x: FAN[i].x, y: '40%', rotate: FAN[i].rotate * 2.2 }}
            animate={{ opacity: 1, x: FAN[i].x, y: FAN[i].y, rotate: FAN[i].rotate }}
            transition={{ duration: 1.3, delay: 0.2 + i * 0.14, ease: EASE_OUT_EXPO }}
          >
            <SlideRenderer scene={scene} scale={width / SLIDE_PX.width} />
          </motion.div>
        ))}
    </div>
  )
}

/** Левая половина: обложка, как у издания */
function Cover() {
  return (
    <aside className="relative hidden flex-col overflow-hidden bg-foreground px-10 py-9 text-background lg:flex xl:px-14">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-3">
          <BrandMark className="bg-background text-foreground" />
          <span className="font-display text-[19px] tracking-[-0.01em]">Презентатор</span>
        </span>
        <span className="eyebrow !text-background/45">Прототип · {new Date().getFullYear()}</span>
      </div>

      <div className="relative my-8 min-h-[260px] flex-1">
        <SlideFan />
      </div>

      <div>
        <span className="block overflow-hidden pb-[0.08em]">
          <motion.span
            className="block font-display text-[clamp(2.6rem,4.4vw,4.4rem)] leading-[0.98] font-[340] tracking-[-0.035em]"
            initial={{ y: '105%' }}
            animate={{ y: '0%' }}
            transition={{ duration: 1.1, delay: 0.15, ease: EASE_OUT_EXPO }}
          >
            Из доклада —
          </motion.span>
        </span>
        <span className="block overflow-hidden pb-[0.08em]">
          <motion.span
            className="block font-display text-[clamp(2.6rem,4.4vw,4.4rem)] leading-[0.98] font-[340] tracking-[-0.035em] italic"
            initial={{ y: '105%' }}
            animate={{ y: '0%' }}
            transition={{ duration: 1.1, delay: 0.25, ease: EASE_OUT_EXPO }}
          >
            в презентацию.
          </motion.span>
        </span>
        <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 border-t border-background/15 pt-5 text-[13px] text-background/60">
          <span>Единое оформление слайдов</span>
          <span>Правка командами</span>
          <span>Редактируемый PPTX</span>
        </div>
      </div>
    </aside>
  )
}

/** Переключатель «Вход / Регистрация» с бегущим подчёркиванием */
function KindSwitch({ kind, disabled, onChange }: { kind: AuthKind; disabled: boolean; onChange: (kind: AuthKind) => void }) {
  return (
    <div className="flex gap-7 border-b border-border" role="group" aria-label="Режим">
      {(['login', 'register'] as const).map((value) => (
        <button
          key={value}
          type="button"
          disabled={disabled}
          aria-pressed={kind === value}
          onClick={() => kind !== value && onChange(value)}
          className={cn(
            'relative -mb-px pb-3 text-[13.5px] font-medium transition-colors outline-none focus-visible:text-foreground disabled:opacity-50',
            kind === value ? 'text-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {COPY[value].tab}
          {kind === value && (
            <motion.span layoutId="auth-kind" className="absolute inset-x-0 bottom-0 h-px bg-foreground" transition={{ duration: 0.5, ease: EASE_OUT_EXPO }} />
          )}
        </button>
      ))}
    </div>
  )
}

interface AuthScreenProps {
  kind: AuthKind
  login: string
  password: string
  error: string
  busy: boolean
  onKindChange: (kind: AuthKind) => void
  onLoginChange: (value: string) => void
  onPasswordChange: (value: string) => void
  onSubmit: (event: FormEvent) => void
}

/** Экран входа и регистрации серверного режима */
export function AuthScreen({ kind, login, password, error, busy, onKindChange, onLoginChange, onPasswordChange, onSubmit }: AuthScreenProps) {
  const [revealed, setRevealed] = useState(false)
  const ids = { login: useId(), loginHint: useId(), password: useId(), passwordHint: useId() }
  const copy = COPY[kind]
  const registering = kind === 'register'
  // Сервер считает символы, а не единицы UTF-16: эмодзи — один символ, а не два
  const length = Array.from(password).length
  const enough = length >= PASSWORD_MIN

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <Cover />

      <main className="flex min-h-dvh flex-col px-5 py-6 sm:px-10 sm:py-9">
        <div className="flex items-center justify-between gap-4">
          <span className="lg:invisible">
            <BrandName compact />
          </span>
          <ModeBadges />
        </div>

        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-12">
          <KindSwitch kind={kind} disabled={busy} onChange={onKindChange} />

          <div className="mt-10 mb-9">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={kind}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.45, ease: EASE_OUT_EXPO }}
              >
                <h1 className="font-display text-[clamp(2.1rem,3.4vw,2.75rem)] leading-none whitespace-nowrap font-[340] tracking-[-0.035em]">{copy.title}</h1>
                <p className="mt-4 text-[15px] leading-relaxed text-muted-foreground">{copy.lead}</p>
              </motion.div>
            </AnimatePresence>
          </div>

          <form onSubmit={onSubmit} className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
              <Label htmlFor={ids.login}>Логин</Label>
              <Input
                id={ids.login}
                required
                minLength={3}
                maxLength={64}
                pattern="[a-zA-Z0-9_.\-]{3,64}"
                title="От 3 до 64 символов: латиница, цифры, точка, дефис, подчёркивание"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                autoFocus
                aria-describedby={registering ? ids.loginHint : undefined}
                className="h-11 text-[15px]"
                value={login}
                onChange={(e) => onLoginChange(e.target.value)}
              />
              {registering && (
                <p id={ids.loginHint} className="text-[12.5px] text-muted-foreground">
                  Латиница, цифры, точка, дефис и подчёркивание
                </p>
              )}
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between">
                <Label htmlFor={ids.password}>Пароль</Label>
                <span id={ids.passwordHint} className={cn('text-[12.5px] tabular-nums transition-colors', registering && enough ? 'text-success' : 'text-muted-foreground')}>
                  {registering ? `${Math.min(length, PASSWORD_MIN)} / ${PASSWORD_MIN} символов` : `${PASSWORD_MIN}–${PASSWORD_MAX} символов`}
                </span>
              </div>
              <div className="relative">
                <Input
                  id={ids.password}
                  required
                  type={revealed ? 'text' : 'password'}
                  minLength={PASSWORD_MIN}
                  maxLength={PASSWORD_MAX}
                  autoComplete={registering ? 'new-password' : 'current-password'}
                  aria-describedby={ids.passwordHint}
                  className="h-11 pr-11 text-[15px]"
                  value={password}
                  onChange={(e) => {
                    const short = registering && Array.from(e.target.value).length < PASSWORD_MIN
                    e.target.setCustomValidity(short ? `Пароль — не меньше ${PASSWORD_MIN} символов` : '')
                    onPasswordChange(e.target.value)
                  }}
                />
                <button
                  type="button"
                  onClick={() => setRevealed((v) => !v)}
                  aria-label={revealed ? 'Скрыть пароль' : 'Показать пароль'}
                  aria-pressed={revealed}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:text-foreground"
                >
                  {revealed ? <EyeOff className="size-[18px]" /> : <Eye className="size-[18px]" />}
                </button>
              </div>
              {/* Длинный пароль проще набрать, когда видно, сколько осталось */}
              {registering && (
                <div className="h-px w-full bg-border" aria-hidden>
                  <motion.div
                    className={cn('h-full origin-left', enough ? 'bg-success' : 'bg-foreground')}
                    initial={false}
                    animate={{ scaleX: Math.min(length / PASSWORD_MIN, 1) }}
                    transition={{ duration: 0.4, ease: EASE_OUT_EXPO }}
                  />
                </div>
              )}
            </div>

            <AnimatePresence initial={false}>
              {error && (
                <motion.div
                  key={error}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.35, ease: EASE_OUT_EXPO }}
                  className="overflow-hidden"
                >
                  <p role="alert" className="border-l-2 border-destructive bg-destructive-soft px-3.5 py-2.5 text-[13.5px] leading-snug text-destructive">
                    {error}
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            <Button type="submit" size="xl" disabled={busy} className="group mt-1 w-full justify-between">
              <span>{busy ? copy.pending : copy.submit}</span>
              {busy ? (
                <LoaderCircle className="animate-spin" aria-hidden />
              ) : (
                <ArrowRight className="transition-transform duration-300 group-hover:translate-x-1" aria-hidden />
              )}
            </Button>
          </form>

          <p className="mt-6 text-[13.5px] text-muted-foreground">
            {copy.switchPrompt}{' '}
            <button
              type="button"
              disabled={busy}
              onClick={() => onKindChange(registering ? 'login' : 'register')}
              className="link-draw font-medium text-foreground outline-none disabled:opacity-50"
            >
              {copy.switchAction}
            </button>
          </p>
        </div>

        <p className="mx-auto flex w-full max-w-[400px] items-start gap-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
          <LockKeyhole className="mt-[3px] size-3.5 shrink-0" aria-hidden />
          Сессия хранится на сервере, браузер получает только HttpOnly-cookie. Пароль в браузере не сохраняется.
        </p>
      </main>
    </div>
  )
}

/** Пока проверяется сессия — короткий спокойный экран вместо мигания формы */
export function SessionCheck() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background" role="status" aria-label="Проверяем сессию">
      <BrandMark className="size-10 text-[24px]" />
      <div className="relative h-px w-40 overflow-hidden bg-border" aria-hidden>
        <span className="absolute inset-y-0 left-0 w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] bg-foreground" />
      </div>
      <span className="eyebrow">Проверяем сессию</span>
    </main>
  )
}
