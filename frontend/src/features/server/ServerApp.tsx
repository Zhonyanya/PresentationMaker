import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { MotionConfig, useReducedMotion } from 'motion/react'
import { env } from '@/config/env'
import { createServerApi, type AcceptedJob, type CurrentPresentation, type JobStatus, type LibraryItem, type ServerUser } from '@/api/server-api'
import { toApiError } from '@/api/errors'
import type { GenerateRequest } from '@/domain/presentation'
import { useEditorStore, selectSelectedSlide } from '@/store/editor-store'
import { useFlowStore } from '@/store/flow-store'
import { safeStorage } from '@/lib/storage'
import { usePresentationScenes } from '@/hooks/usePresentationScenes'
import { CreatePage } from '@/features/create/CreatePage'
import { ReadyCurtain } from '@/features/generation/ReadyCurtain'
import { AuthScreen, SessionCheck, type AuthKind } from './AuthScreen'
import { AccountControls, JobWaiting, Library, Notice, PausedJob, ServerEditor, type JobKind } from './ServerWorkspace'
import { useMlStub } from '@/components/app/ModeBadges'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import { toast } from 'sonner'

const api = createServerApi({ baseUrl: env.apiBaseUrl })
const referenceKey = (user: ServerUser) => `pm:current:${user.id}`
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Poll failures worth retrying: the job keeps running on the server meanwhile. */
const TRANSIENT = new Set(['network', 'timeout', 'server', 'rate_limited'])
const POLL_RETRIES = 5

/** crypto.randomUUID exists only in secure contexts (HTTPS/localhost); getRandomValues works everywhere. */
function randomKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
}

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
  const [jobKind, setJobKind] = useState<JobKind>(null)
  const [jobStartedAt, setJobStartedAt] = useState<number | null>(null)
  const [ready, setReady] = useState<number | null>(null)
  const [library, setLibrary] = useState<LibraryItem[]>([])
  const jobKindRef = useRef<JobKind>(null)
  const editorRef = useRef(false)
  const waitingRef = useRef(false)
  waitingRef.current = waiting
  const reduceMotion = useReducedMotion()
  const mlStubRef = useRef(false)
  mlStubRef.current = useMlStub()
  jobKindRef.current = jobKind
  editorRef.current = editor
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
    let presentationId: string
    try {
      const reference: unknown = JSON.parse(raw)
      if (!reference || typeof reference !== 'object' || !('presentationId' in reference) || typeof reference.presentationId !== 'string' || !UUID.test(reference.presentationId)) throw new Error('bad reference')
      presentationId = reference.presentationId
    } catch {
      // Испорченную ссылку не показываем ошибкой при каждом входе — просто забываем
      safeStorage.removeItem(referenceKey(account))
      return
    }
    try {
      const value = await api.current(presentationId)
      if (activeEpoch !== epoch.current) return
      applyCurrent(value)
      // Server active_job is authoritative; completed jobs need no resumed polling.
      setJob(value.active_job)
      setWaiting(Boolean(value.active_job))
      setJobKind(null); setJobStartedAt(value.active_job ? Date.now() : null)
      setEditor(Boolean(value.document))
      saveReference(account, value.presentation_id, value.active_job)
    } catch (cause) {
      if (activeEpoch !== epoch.current) return
      const error = toApiError(cause)
      // Презентации больше нет — ссылка устарела, ошибка тут не нужна
      if (error.code === 'not_found' || error.code === 'validation') safeStorage.removeItem(referenceKey(account))
      else setError(error.message)
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
      clearPrivate(); setError('Сессия завершена. Войдите снова.')
    }
    // Covers cookie changes made outside this app, as well as session expiry in a background tab.
    // The same user signing in again elsewhere keeps this tab's unsent work; only the CSRF token
    // of the rotated session is refetched.
    const recheck = async () => {
      try {
        const account = await api.me()
        if (account.id !== userRef.current?.id) { clearPrivate(); void bootstrap() }
        else api.resetCsrf()
      } catch { /* 401 is handled by the shared event; transient network failure keeps the view. */ }
    }
    const changed = (event: StorageEvent) => {
      if (event.key === 'pm:auth-change') void recheck()
    }
    const focus = () => void recheck()
    window.addEventListener('pm:unauthorized', unauthorized)
    window.addEventListener('storage', changed)
    window.addEventListener('focus', focus)
    return () => { mounted = false; window.removeEventListener('pm:unauthorized', unauthorized); window.removeEventListener('storage', changed); window.removeEventListener('focus', focus) }
  }, [clearPrivate, restore])

  const jobId = job?.job_id
  const jobPresentationId = job?.presentation_id
  useEffect(() => {
    // Опрос идёт и при приостановленном ожидании (реже): иначе интерфейс считал бы задание
    // выполняющимся вечно и не давал начать новое
    if (!jobId || !jobPresentationId || !user) return
    const controller = new AbortController()
    const activeEpoch = epoch.current
    let timer: ReturnType<typeof setTimeout>
    let failures = 0
    const later = (ms: number) => { timer = setTimeout(() => void poll(), ms) }
    const poll = async () => {
      try {
        const status = await api.status(jobId, controller.signal)
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        failures = 0
        setPhase(status.phase)
        if (status.status === 'queued' || status.status === 'running') {
          later(!waitingRef.current || globalThis.document.hidden ? 10000 : 2500)
          return
        }
        const value = await api.current(jobPresentationId, controller.signal)
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        // Документ ещё не успел отметить завершение этого задания — спросим чуть позже
        if (value.active_job?.job_id === jobId) {
          later(2500)
          return
        }
        const paused = !waitingRef.current && !editorRef.current
        applyCurrent(value)
        setJob(value.active_job); setWaiting(Boolean(value.active_job))
        saveReference(user, value.presentation_id, value.active_job)
        const kind = jobKindRef.current
        setJobKind(null)
        if (status.status === 'succeeded' && paused) {
          // Пользователь ушёл к форме: не перебрасываем его, а предлагаем открыть результат
          setInstruction('')
          toast.success(kind === 'revise' ? 'Правка применена' : 'Презентация готова', {
            action: { label: 'Открыть', onClick: () => setEditor(true) },
          })
        } else if (status.status === 'succeeded') {
          // Moment of "Готово" between waiting and the editor, as in the demo flow
          if (value.document && kind !== 'revise' && !editorRef.current) setReady(value.document.slides.length)
          if (kind === 'revise') {
            toast.success('Правка применена', mlStubRef.current
              ? { description: 'Тестовая заглушка ML меняет только заметки докладчика к выбранным слайдам.' }
              : undefined)
          }
          setEditor(Boolean(value.document))
          setInstruction('')
          setError(status.output_document_token !== value.document_token ? 'Документ уже обновлён другой задачей. Показан текущий результат, не архив.' : '')
        } else setError(status.error?.message ?? 'Задание завершилось с ошибкой. Предыдущий документ сохранён.')
      } catch (cause) {
        if (controller.signal.aborted || activeEpoch !== epoch.current) return
        const error = toApiError(cause)
        // Разовый сбой сети или прокси не повод бросать ожидание: повторяем с растущей паузой
        if (TRANSIENT.has(error.code) && failures < POLL_RETRIES) {
          failures++
          later(Math.min(2500 * 2 ** failures, 30000))
          return
        }
        setError(`${error.message} Остановка ожидания не отменяет задание.`)
        setWaiting(false)
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [jobId, jobPresentationId, user, waiting, applyCurrent])

  const refreshLibrary = useCallback(async () => {
    try {
      setLibrary(await api.list())
    } catch {
      /* Список вторичен: ошибка сети не должна заслонять основной сценарий */
    }
  }, [])
  // Обновляем после входа, завершения задания и смены документа
  const documentToken = current?.document_token
  useEffect(() => {
    if (user) void refreshLibrary()
    else setLibrary([])
  }, [user, jobId, documentToken, refreshLibrary])

  const authenticate = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    const activeEpoch = epoch.current
    try {
      const account = await api.authenticate(authKind, login, password)
      if (activeEpoch !== epoch.current) return
      clearPrivate()
      userRef.current = account; setUser(account)
      safeStorage.setItem('pm:auth-change', randomKey())
      await restore(account, epoch.current)
    } catch (cause) { if (activeEpoch === epoch.current) setError(toApiError(cause).message) }
    finally { setPassword(''); setBusy(false) }
  }

  const logout = async () => {
    setBusy(true)
    try {
      await api.logout()
      // На общем компьютере следующий человек не должен видеть ссылку на чужую работу
      if (userRef.current) safeStorage.removeItem(referenceKey(userRef.current))
      clearPrivate()
      safeStorage.setItem('pm:auth-change', randomKey())
    } catch (cause) { setError(toApiError(cause).message) }
    finally { setBusy(false) }
  }

  const launch = async (operation: 'generate' | 'revise', body?: GenerateRequest) => {
    if (!user || busy) return
    if (job) {
      setError('Дождитесь завершения текущего задания — оно ещё выполняется на сервере.')
      return
    }
    const activeEpoch = epoch.current
    setBusy(true); setError('')
    try {
      const numbers = targets.trim() ? targets.split(',').map((n) => Number(n.trim())) : undefined
      if (operation === 'revise' && (!instruction.trim() || (numbers && (new Set(numbers).size !== numbers.length || numbers.some((n) => !Number.isInteger(n) || n < 1 || n > (current?.slide_count ?? 0)))))) {
        throw new Error('Введите команду и уникальные номера существующих слайдов через запятую.')
      }
      const signature = JSON.stringify({ operation, body, instruction, numbers, id: current?.presentation_id, token: current?.document_token })
      if (submission.current?.signature !== signature) submission.current = { signature, key: randomKey() }
      const key = submission.current.key
      const accepted = operation === 'generate' && body ? await api.generate(body, key, undefined, current ?? undefined)
        : await api.revise(current!, instruction, numbers, key)
      if (activeEpoch !== epoch.current) return
      submission.current = null
      setJob(accepted); setWaiting(true); setPhase('waiting')
      setJobKind(operation); setJobStartedAt(Date.now())
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

  // Новый экран открывается с начала: иначе на телефоне заголовок ожидания и превью
  // слайда оказываются выше видимой области. Форма сама прокручивается к рабочей области.
  const screenKind = editor ? 'editor' : job && waiting ? 'waiting' : 'create'
  useLayoutEffect(() => {
    if (screenKind !== 'create') window.scrollTo(0, 0)
  }, [screenKind])

  if (initializing) return <SessionCheck />
  if (!user) return <AuthScreen kind={authKind} login={login} password={password} error={error} busy={busy}
    onKindChange={(kind) => { setAuthKind(kind); setError('') }} onLoginChange={setLogin} onPasswordChange={setPassword}
    onSubmit={(e) => void authenticate(e)} />

  const document = current?.document
  // Store and server state update separately; for one render the selection may point to another document
  const selectedIndex = Math.max(0, document?.slides.findIndex((s) => s.id === selected?.id) ?? 0)
  const startNew = () => {
    setCurrent(null); setEditor(false); setInstruction(''); setTargets(''); setError(''); submission.current = null
    useEditorStore.getState().close(); useFlowStore.getState().clearDraft(); safeStorage.removeItem(referenceKey(user))
  }
  const leaveWaiting = () => { setWaiting(false); setEditor(false) }
  const openPresentation = async (id: string) => {
    const activeEpoch = epoch.current
    setBusy(true); setError('')
    try {
      const value = await api.current(id)
      if (activeEpoch !== epoch.current) return
      applyCurrent(value); setJob(value.active_job); setWaiting(Boolean(value.active_job)); setJobKind(null)
      setJobStartedAt(value.active_job ? Date.now() : null)
      setEditor(Boolean(value.document)); setInstruction(''); setTargets(''); submission.current = null
      saveReference(user, value.presentation_id, value.active_job)
    } catch (cause) {
      if (activeEpoch === epoch.current) setError(toApiError(cause).message)
    } finally { if (activeEpoch === epoch.current) setBusy(false) }
  }
  const deletePresentation = async (id: string) => {
    setBusy(true); setError('')
    try {
      await api.remove(id)
      if (current?.presentation_id === id) startNew()
      toast.success('Презентация удалена')
      void refreshLibrary()
    } catch (cause) {
      setError(toApiError(cause).message)
    } finally { setBusy(false) }
  }
  const deleteAccount = async (accountPassword: string): Promise<string | null> => {
    setBusy(true)
    try {
      await api.deleteAccount(accountPassword)
      safeStorage.removeItem(referenceKey(user))
      clearPrivate()
      safeStorage.setItem('pm:auth-change', randomKey())
      toast.success('Аккаунт и все данные удалены')
      return null
    } catch (cause) {
      return toApiError(cause).message
    } finally { setBusy(false) }
  }
  const resumeWaiting = () => setWaiting(true)
  const account = <AccountControls login={user.login} busy={busy} canStartNew={!busy && !job} onNew={startNew} onLogout={() => void logout()} />
  const notice = error ? (
    <Notice
      message={error}
      onDismiss={() => setError('')}
      action={current && <Button variant="link" size="sm" className="h-auto shrink-0 text-destructive" onClick={() => void refresh()}>Обновить документ</Button>}
    />
  ) : null

  let screen
  if (editor && document && selected) {
    screen = (
      <ServerEditor
        document={document}
        scenes={scenes}
        selected={document.slides[selectedIndex] ?? selected}
        selectedIndex={selectedIndex}
        account={account}
        notice={notice}
        job={job ? { phase, waiting, onLeave: leaveWaiting, onResume: resumeWaiting } : null}
        exportOpen={exportOpen}
        onExportOpenChange={setExportOpen}
        onSelect={(id) => useEditorStore.getState().select(id)}
        onBack={() => setEditor(false)}
        busy={busy}
        instruction={instruction}
        targets={targets}
        onInstruction={setInstruction}
        onTargets={setTargets}
        onRevise={() => void launch('revise')}
        onRegenerate={leaveWaiting}
      />
    )
  } else if (job && waiting) {
    screen = <JobWaiting phase={phase} kind={jobKind} startedAt={jobStartedAt} header={account} notice={notice} onLeave={leaveWaiting} />
  } else {
    screen = (
      <CreatePage
        serverMode
        headerSlot={account}
        startAtWorkspace={Boolean(job || current)}
        notice={<>
          {notice}
          {job && <PausedJob phase={phase} onResume={resumeWaiting} />}
          <Library items={library} currentId={current?.presentation_id ?? null} busy={busy || Boolean(job)}
            onOpen={(id) => void openPresentation(id)} onDelete={(id) => void deletePresentation(id)} onDeleteAccount={deleteAccount} />
        </>}
        onGenerate={(body) => void launch('generate', body)}
        onOpenCurrent={() => setEditor(true)}
        onDiscardCurrent={startNew}
      />
    )
  }

  return <>
    {screen}
    {ready !== null && !reduceMotion && <ReadyCurtain slideCount={ready} onDone={() => setReady(null)} />}
  </>
}
