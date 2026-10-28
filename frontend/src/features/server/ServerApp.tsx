import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { MotionConfig } from 'motion/react'
import { env } from '@/config/env'
import { createServerApi, type AcceptedJob, type CurrentPresentation, type JobStatus, type ServerUser } from '@/api/server-api'
import { toApiError } from '@/api/errors'
import type { GenerateRequest } from '@/domain/presentation'
import { useEditorStore, selectSelectedSlide } from '@/store/editor-store'
import { useFlowStore } from '@/store/flow-store'
import { safeStorage } from '@/lib/storage'
import { usePresentationScenes } from '@/hooks/usePresentationScenes'
import { CreatePage } from '@/features/create/CreatePage'
import { EditorHeader } from '@/features/editor/EditorHeader'
import { SlideCanvas } from '@/features/editor/SlideCanvas'
import { ExportDialog } from '@/features/editor/ExportDialog'
import { SlideRenderer, SLIDE_PX } from '@/features/slides/SlideRenderer'
import { AuthScreen, SessionCheck, type AuthKind } from './AuthScreen'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'

const api = createServerApi({ baseUrl: env.apiBaseUrl })
const referenceKey = (user: ServerUser) => `pm:current:${user.id}`
const PHASES: Record<JobStatus['phase'], string> = { waiting: 'В очереди', ml: 'Выполняется ML', validation: 'Проверяем результат', saving: 'Сохраняем', done: 'Завершено' }

/** Only references are persisted, never source text, commands, passwords or documents. */
function saveReference(user: ServerUser, presentationId: string, job: AcceptedJob | null) {
  safeStorage.setItem(referenceKey(user), JSON.stringify({ presentationId, job }))
}

export function ServerApp() {
  return <MotionConfig reducedMotion="user"><TooltipProvider><Workspace /><Toaster /></TooltipProvider></MotionConfig>
}

function Workspace() {
  const [user, setUser] = useState<ServerUser | null>(null)
  const [initializing, setInitializing] = useState(true)
  const [authKind, setAuthKind] = useState<AuthKind>('login')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [current, setCurrent] = useState<CurrentPresentation | null>(null)
  const [job, setJob] = useState<AcceptedJob | null>(null)
  const [phase, setPhase] = useState<JobStatus['phase']>('waiting')
  const [waiting, setWaiting] = useState(false)
  const [editor, setEditor] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [targets, setTargets] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const epoch = useRef(0)
  const userRef = useRef<ServerUser | null>(null)
  const submission = useRef<{ signature: string; key: string } | null>(null)
  const selected = useEditorStore(selectSelectedSlide)
  const scenes = usePresentationScenes(current?.document?.slides ?? [])

  const clearPrivate = useCallback(() => {
    epoch.current++
    api.forget()
    userRef.current = null
    submission.current = null
    setUser(null); setCurrent(null); setJob(null); setWaiting(false); setEditor(false)
    setInstruction(''); setTargets(''); setPassword(''); setLogin(''); setError(''); setBusy(false); setExportOpen(false)
    useEditorStore.getState().close()
    useFlowStore.getState().clearDraft()
  }, [])

  const applyCurrent = useCallback((value: CurrentPresentation) => {
    setCurrent(value)
    if (value.document) useEditorStore.getState().load(value.document)
    else useEditorStore.getState().close()
  }, [])

  const restore = useCallback(async (account: ServerUser, activeEpoch: number) => {
    const raw = await safeStorage.getItem(referenceKey(account))
    if (!raw) return
    try {
      const reference: unknown = JSON.parse(raw)
      if (!reference || typeof reference !== 'object' || !('presentationId' in reference) || typeof reference.presentationId !== 'string') return
      const value = await api.current(reference.presentationId)
      if (activeEpoch !== epoch.current) return
      applyCurrent(value)
      // Server active_job is authoritative; completed jobs need no resumed polling.
      setJob(value.active_job)
      setWaiting(Boolean(value.active_job))
      setEditor(Boolean(value.document))
      saveReference(account, value.presentation_id, value.active_job)
    } catch (cause) {
      if (activeEpoch === epoch.current) setError(toApiError(cause).message)
    }
  }, [applyCurrent])

  useEffect(() => {
    let mounted = true
    const bootstrap = async () => {
      const activeEpoch = epoch.current
      try {
        const account = await api.me()
        if (!mounted || activeEpoch !== epoch.current) return
        userRef.current = account; setUser(account)
        await restore(account, activeEpoch)
      } catch (cause) {
        // 401 here just means "not signed in"; 'aborted' means a newer identity superseded this request.
        const { code, message } = toApiError(cause)
        if (mounted && code !== 'unauthorized' && code !== 'aborted') setError(message)
      } finally { if (mounted) setInitializing(false) }
    }
    void bootstrap()
    // Without a signed-in user there is no session to expire and no private state to clear;
    // resetting anyway would also abort the parallel bootstrap request.
    const unauthorized = () => {
      if (!userRef.current) return
      clearPrivate(); setError('Сессия истекла. Войдите снова.')
    }
    const changed = (event: StorageEvent) => {
      if (event.key === 'pm:auth-change') { clearPrivate(); void bootstrap() }
    }
    // Covers cookie changes made outside this app, as well as session expiry in a background tab.
    const focus = async () => {
      try {
        const account = await api.me()
        if (account.id !== userRef.current?.id) { clearPrivate(); void bootstrap() }
      } catch { /* 401 is handled by the shared event; transient network failure keeps the view. */ }
    }
    window.addEventListener('pm:unauthorized', unauthorized)
    window.addEventListener('storage', changed)
    window.addEventListener('focus', focus)
    return () => { mounted = false; window.removeEventListener('pm:unauthorized', unauthorized); window.removeEventListener('storage', changed); window.removeEventListener('focus', focus) }
  }, [clearPrivate, restore])

  useEffect(() => {
    if (!job || !user || !waiting) return
    const controller = new AbortController()
    const activeEpoch = epoch.current
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const status = await api.status(job.job_id, controller.signal)
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        setPhase(status.phase)
        if (status.status === 'queued' || status.status === 'running') {
          timer = setTimeout(() => void poll(), globalThis.document.hidden ? 10000 : 2500)
          return
        }
        const value = await api.current(job.presentation_id, controller.signal)
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        applyCurrent(value)
        setJob(value.active_job); setWaiting(Boolean(value.active_job))
        saveReference(user, value.presentation_id, value.active_job)
        if (status.status === 'succeeded') {
          setEditor(Boolean(value.document))
          setInstruction('')
          setError(status.output_document_token !== value.document_token ? 'Документ уже обновлён другой задачей. Показан текущий результат, не архив.' : '')
        } else setError(status.error?.message ?? 'Задание завершилось с ошибкой. Предыдущий документ сохранён.')
      } catch (cause) {
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        setError(`${toApiError(cause).message} Остановка ожидания не отменяет задание.`)
        setWaiting(false)
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [job, user, waiting, applyCurrent])

  const authenticate = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    const activeEpoch = epoch.current
    try {
      const account = await api.authenticate(authKind, login, password)
      if (activeEpoch !== epoch.current) return
      clearPrivate()
      userRef.current = account; setUser(account)
      safeStorage.setItem('pm:auth-change', crypto.randomUUID())
      await restore(account, epoch.current)
    } catch (cause) { if (activeEpoch === epoch.current) setError(toApiError(cause).message) }
    finally { setPassword(''); setBusy(false) }
  }

  const logout = async () => {
    setBusy(true)
    try {
      await api.logout()
      clearPrivate()
      safeStorage.setItem('pm:auth-change', crypto.randomUUID())
    } catch (cause) { setError(toApiError(cause).message) }
    finally { setBusy(false) }
  }

  const launch = async (operation: 'generate' | 'revise', body?: GenerateRequest) => {
    if (!user || busy || job) return
    const activeEpoch = epoch.current
    setBusy(true); setError('')
    try {
      const numbers = targets.trim() ? targets.split(',').map((n) => Number(n.trim())) : undefined
      if (operation === 'revise' && (!instruction.trim() || (numbers && (new Set(numbers).size !== numbers.length || numbers.some((n) => !Number.isInteger(n) || n < 1 || n > (current?.slide_count ?? 0)))))) {
        throw new Error('Введите команду и уникальные номера существующих слайдов через запятую.')
      }
      const signature = JSON.stringify({ operation, body, instruction, numbers, id: current?.presentation_id, token: current?.document_token })
      if (submission.current?.signature !== signature) submission.current = { signature, key: crypto.randomUUID() }
      const key = submission.current.key
      const accepted = operation === 'generate' && body ? await api.generate(body, key, undefined, current ?? undefined)
        : await api.revise(current!, instruction, numbers, key)
      if (activeEpoch !== epoch.current) return
      submission.current = null
      setJob(accepted); setWaiting(true); setPhase('waiting')
      saveReference(user, accepted.presentation_id, accepted)
      // Polling loads the document after completion. An eager GET here could
      // arrive late with document: null and overwrite the successful result.
    } catch (cause) {
      if (activeEpoch !== epoch.current) return
      setError(cause instanceof Error && cause.name === 'Error' ? cause.message : toApiError(cause).message)
    } finally { if (activeEpoch === epoch.current) setBusy(false) }
  }

  const refresh = async () => {
    if (!current || !user) return
    const activeEpoch = epoch.current
    try {
      const value = await api.current(current.presentation_id)
      if (activeEpoch !== epoch.current) return
      applyCurrent(value); setJob(value.active_job); setWaiting(Boolean(value.active_job)); setError('')
      saveReference(user, value.presentation_id, value.active_job)
    } catch (cause) { if (activeEpoch === epoch.current) setError(toApiError(cause).message) }
  }

  if (initializing) return <SessionCheck />
  if (!user) return <AuthScreen kind={authKind} login={login} password={password} error={error} busy={busy}
    onKindChange={(kind) => { setAuthKind(kind); setError('') }} onLoginChange={setLogin} onPasswordChange={setPassword}
    onSubmit={(e) => void authenticate(e)} />

  const document = current?.document
  const selectedIndex = document?.slides.findIndex((s) => s.id === selected?.id) ?? 0
  return <>
    <div className="flex flex-wrap items-center justify-end gap-3 border-b bg-background px-5 py-2 text-sm">
      <span>{user.login}</span>
      <Button variant="ghost" size="sm" disabled={busy || Boolean(job)} onClick={() => {
        setCurrent(null); setEditor(false); setInstruction(''); setTargets(''); submission.current = null
        useEditorStore.getState().close(); useFlowStore.getState().clearDraft(); safeStorage.removeItem(referenceKey(user))
      }}>Новая презентация</Button>
      <Button variant="ghost" size="sm" onClick={() => void logout()} disabled={busy}>Выйти</Button>
    </div>
    {(error || job) && <section className="border-b bg-card px-5 py-4" aria-live="polite">
      {error && <p role="alert" className="mb-2 text-destructive">{error}</p>}
      {job && <div className="flex flex-wrap items-center gap-3"><span>{waiting ? PHASES[phase] : 'Ожидание приостановлено'}. Задание продолжит выполняться на сервере.</span>
        {waiting ? <Button variant="outline" onClick={() => { setWaiting(false); setEditor(false) }}>Вернуться к форме</Button>
          : <Button onClick={() => setWaiting(true)}>Возобновить ожидание</Button>}</div>}
      {current && <Button variant="link" onClick={() => void refresh()}>Обновить текущий документ</Button>}
    </section>}
    {editor && document && selected ? <div className="flex min-h-dvh flex-col bg-background">
      <EditorHeader title={document.title} onBack={() => setEditor(false)} onExport={() => setExportOpen(true)} />
      <div className="grid min-h-[70vh] grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_320px]">
        <nav className="scroll-thin flex gap-4 overflow-auto border-r p-4 lg:max-h-[85vh] lg:flex-col" aria-label="Слайды">
          {document.slides.map((slide, index) => <button key={slide.id} onClick={() => useEditorStore.getState().select(slide.id)} aria-pressed={selected.id === slide.id} aria-label={`Слайд ${index + 1}: ${slide.title}`} className={`shrink-0 p-1 text-left ${selected.id === slide.id ? 'ring-2 ring-foreground' : ''}`}>
            <span className="text-xs">{index + 1}. {slide.title}</span><div className="pointer-events-none"><SlideRenderer scene={scenes[index]} scale={176 / SLIDE_PX.width} /></div>
          </button>)}
        </nav>
        <SlideCanvas slide={selected} scene={scenes[selectedIndex]} index={selectedIndex} total={document.slides.length} activeField={null} readOnly />
        <aside className="space-y-5 border-l p-5">
          <h2 className="font-display text-2xl">Правка командой</h2>
          <p className="text-sm text-muted-foreground">Изменения выполняет ML. Пока задача не завершится успешно, прежний результат доступен для просмотра и экспорта.</p>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void launch('revise') }}>
            <Label htmlFor="command">Что изменить</Label><Textarea id="command" required maxLength={10000} value={instruction} onChange={(e) => setInstruction(e.target.value)} disabled={busy || Boolean(job)} />
            <Label htmlFor="targets">Номера слайдов через запятую (необязательно)</Label><Input id="targets" value={targets} onChange={(e) => setTargets(e.target.value)} disabled={busy || Boolean(job)} placeholder="Например: 2, 4" />
            <Button disabled={busy || Boolean(job) || !instruction.trim()}>Применить команду</Button>
          </form>
          <Button variant="outline" onClick={() => { setWaiting(false); setEditor(false) }}>Полная перегенерация</Button>
        </aside>
      </div>
      <ExportDialog open={exportOpen} onOpenChange={setExportOpen} presentation={document} scenes={scenes} />
    </div> : <CreatePage serverMode onGenerate={(body) => void launch('generate', body)} onOpenCurrent={() => setEditor(true)} />}
  </>
}
