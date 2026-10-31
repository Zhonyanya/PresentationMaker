import { useRef, useState, type DragEvent } from 'react'
import { ClipboardPaste, FileUp, Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { LIMITS } from '@/domain/presentation'
import { ACCEPTED_FILE_TYPES } from '@/lib/file-import'
import { cn, formatNumber, plural } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { useSourceFileImport } from './useSourceFileImport'

interface SourceTextFieldProps {
  id: string
  value: string
  onChange: (value: string) => void
  error?: string
  onSubmitShortcut: () => void
  onShowExamples: () => void
}

export function SourceTextField({ id, value, onChange, error, onSubmitShortcut, onShowExamples }: SourceTextFieldProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const { importFile, loading } = useSourceFileImport((text) => {
    onChange(text)
    textareaRef.current?.focus()
  })

  const length = value.length
  const words = value.trim() ? value.trim().split(/\s+/).length : 0
  const overLimit = length > LIMITS.sourceTextMax
  const empty = value.trim() === ''
  const errorId = `${id}-error`
  const hintId = `${id}-hint`

  const pasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (!text.trim()) {
        toast('Буфер обмена пуст', { description: 'Скопируйте текст доклада и попробуйте снова.' })
        return
      }
      onChange(text)
      textareaRef.current?.focus()
    } catch {
      textareaRef.current?.focus()
      toast('Нет доступа к буферу обмена', { description: 'Вставьте текст сочетанием клавиш Ctrl+V (⌘V на Mac).' })
    }
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) void importFile(file)
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <Label htmlFor={id} className="eyebrow">
          Текст доклада или план выступления
        </Label>
        <div className="-mx-2 flex items-center gap-1 sm:mx-0">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_FILE_TYPES}
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void importFile(file)
              e.target.value = ''
            }}
          />
          <Button type="button" variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <FileUp />}
            Загрузить файл
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => { onChange(''); textareaRef.current?.focus() }} disabled={empty}>
            <Trash2 />
            Очистить
          </Button>
        </div>
      </div>

      <div
        className={cn(
          'relative transition-[box-shadow]',
          dragging && 'ring-1 ring-foreground',
        )}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault()
            setDragging(true)
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <textarea
          ref={textareaRef}
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
              e.preventDefault()
              onSubmitShortcut()
            }
          }}
          aria-invalid={Boolean(error) || overLimit}
          aria-describedby={`${hintId}${error ? ` ${errorId}` : ''}`}
          spellCheck
          className={cn(
            'scroll-thin block h-[clamp(340px,52vh,560px)] w-full resize-y rounded-[3px] border border-input bg-card px-6 py-5 text-[15.5px] leading-[1.75] outline-none transition-[border-color] duration-300',
            'hover:border-[#a9a191] focus-visible:border-foreground',
            'aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive/15',
          )}
        />

        {empty && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
            <div className="flex max-w-[440px] flex-col items-center text-center">
              <span className="mb-5 font-display text-[44px] leading-none text-foreground/15 italic" aria-hidden>
                ¶
              </span>
              <p className="font-display text-[22px] leading-tight font-[380] tracking-[-0.01em] text-foreground">Вставьте текст доклада или план выступления</p>
              <p className="mt-3 text-[13.5px] leading-relaxed text-muted-foreground">
                Подойдёт текст из Word, тезисы или пронумерованный план. Заголовки разделов помогут точнее разбить материал на слайды.
              </p>
              <div className="pointer-events-auto mt-7 flex flex-wrap items-center justify-center gap-x-6 gap-y-3">
                <Button type="button" variant="outline" size="sm" onClick={pasteFromClipboard}>
                  <ClipboardPaste />
                  Вставить из буфера
                </Button>
                <Button type="button" variant="link" size="sm" onClick={() => fileInputRef.current?.click()}>
                  Загрузить .txt, .md или .docx
                </Button>
                <Button type="button" variant="link" size="sm" onClick={onShowExamples}>
                  Открыть пример
                </Button>
              </div>
            </div>
          </div>
        )}

        {dragging && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center border border-dashed border-foreground bg-card/95 font-display text-[20px] italic">
            Отпустите файл, чтобы загрузить текст
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 text-xs">
        <div className="min-h-4">
          {error ? (
            <p id={errorId} role="alert" className="font-medium text-destructive">
              {error}
            </p>
          ) : (
            <p id={hintId} className="text-muted-foreground">
              Можно перетащить файл в поле. Поддерживаются .txt, .md и .docx.
            </p>
          )}
        </div>
        <p className={cn('tabular-nums text-muted-foreground', overLimit && 'font-medium text-destructive')} aria-live="polite">
          {formatNumber(length)} / {formatNumber(LIMITS.sourceTextMax)} {plural(LIMITS.sourceTextMax, ['символ', 'символа', 'символов'])}
          {words > 0 && <span className="text-muted-foreground"> · {formatNumber(words)} {plural(words, ['слово', 'слова', 'слов'])}</span>}
        </p>
      </div>
    </div>
  )
}
