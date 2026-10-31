import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Download, FileCheck2, Loader2, TriangleAlert } from 'lucide-react'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import { toast } from 'sonner'
import type { Presentation } from '@/domain/presentation'
import type { SlideScene } from '@/layouts/scene'
import { sceneHasOverflow } from '@/hooks/usePresentationScenes'
import { downloadPptx, toFileName } from '@/export/pptx-export'
import { presentationTheme } from '@/theme/presentation-theme'
import { plural } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useEditorStore } from '@/store/editor-store'

interface ExportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  presentation: Presentation
  scenes: SlideScene[]
}

export function ExportDialog({ open, onOpenChange, presentation, scenes }: ExportDialogProps) {
  const select = useEditorStore((s) => s.select)
  const [fileName, setFileName] = useState('')
  const [includeNotes, setIncludeNotes] = useState(true)
  const [busy, setBusy] = useState(false)
  /** Имя сохранённого файла — показываем подтверждение перед закрытием окна */
  const [savedName, setSavedName] = useState<string | null>(null)

  useEffect(() => {
    if (!savedName) return
    const timer = window.setTimeout(() => onOpenChange(false), 1700)
    return () => window.clearTimeout(timer)
  }, [savedName, onOpenChange])

  useEffect(() => {
    if (open) setSavedName(null)
  }, [open])

  useEffect(() => {
    if (open) setFileName(toFileName(presentation.title).replace(/\.pptx$/, ''))
  }, [open, presentation.title])

  const problems = presentation.slides
    .map((slide, index) => ({ slide, index, overflow: sceneHasOverflow(scenes[index]) }))
    .filter((item) => item.overflow)
  const notesCount = presentation.slides.filter((s) => s.notes?.trim()).length
  const count = presentation.slides.length

  const download = async () => {
    setBusy(true)
    try {
      const name = await downloadPptx(presentation, fileName, { includeNotes })
      setSavedName(name)
    } catch (error) {
      console.error('[export]', error)
      toast.error('Не удалось сформировать файл', { description: 'Попробуйте ещё раз. Если ошибка повторится, сообщите разработчикам.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent>
        {savedName ? (
          <motion.div
            role="status"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: EASE_OUT_EXPO }}
            className="flex flex-col items-center py-6 text-center"
          >
            <svg viewBox="0 0 64 64" className="size-16" fill="none" stroke="currentColor" strokeWidth={1.4} aria-hidden>
              <motion.circle cx="32" cy="32" r="30" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.8, ease: EASE_OUT_EXPO }} />
              <motion.path
                d="M20 33l8 8 16-18"
                strokeWidth={1.8}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.5, delay: 0.45, ease: EASE_OUT_EXPO }}
              />
            </svg>
            <DialogTitle className="mt-6 italic">Файл готов</DialogTitle>
            <DialogDescription className="mt-2 max-w-[36ch] break-all">{savedName}</DialogDescription>
          </motion.div>
        ) : (
        <>
        <DialogHeader>
          <DialogTitle>Скачать презентацию</DialogTitle>
          <DialogDescription>
            Файл PPTX открывается в PowerPoint и совместимых редакторах. Тексты, фигуры и заметки остаются редактируемыми.
          </DialogDescription>
        </DialogHeader>

        <form
          id="export-form"
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            void download()
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="export-file-name">Имя файла</Label>
            <div className="flex items-center">
              <Input
                id="export-file-name"
                value={fileName}
                onChange={(e) => setFileName(e.target.value)}
                className="rounded-r-none shadow-none focus-visible:ring-0"
                autoComplete="off"
                spellCheck={false}
              />
              <span className="inline-flex h-9 items-center border border-l-0 border-input bg-muted px-3 text-sm text-muted-foreground">.pptx</span>
            </div>
          </div>

          <div className="flex items-center justify-between gap-4 border-y border-border py-4">
            <Label htmlFor="export-notes" className="flex-col items-start gap-1">
              <span>Заметки докладчика</span>
              <span className="text-xs font-normal text-muted-foreground">
                {notesCount ? `Есть у ${notesCount} ${plural(notesCount, ['слайда', 'слайдов', 'слайдов'])}` : 'Заметок пока нет'}
              </span>
            </Label>
            <Switch id="export-notes" checked={includeNotes} onCheckedChange={setIncludeNotes} />
          </div>

          <dl className="grid grid-cols-3 text-[12.5px]">
            {[
              ['Слайдов', String(count)],
              ['Формат', '16:9'],
              ['Оформление', presentationTheme.isOfficial ? presentationTheme.name : 'Временное'],
            ].map(([term, value]) => (
              <div key={term} className="flex flex-col gap-1.5 border-l border-border pl-4 first:border-l-0 first:pl-0">
                <dt className="eyebrow !text-[10px]">{term}</dt>
                <dd className="font-display text-[22px] leading-none">{value}</dd>
              </div>
            ))}
          </dl>

          {problems.length > 0 ? (
            <div className="border-l-2 border-warning bg-warning-soft/60 px-4 py-3 text-[13px]">
              <p className="flex items-center gap-2 font-medium text-warning">
                <TriangleAlert className="size-4" aria-hidden />
                Слишком много текста на {problems.length} {plural(problems.length, ['слайде', 'слайдах', 'слайдах'])}
              </p>
              <p className="mt-1 text-muted-foreground">Файл можно скачать: текст останется в границах слайда, но шрифт будет мелким.</p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {problems.map(({ slide, index }) => (
                  <li key={slide.id}>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7"
                      onClick={() => {
                        select(slide.id)
                        onOpenChange(false)
                      }}
                    >
                      Слайд {index + 1}
                    </Button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-[13px] text-success">
              <FileCheck2 className="size-4" aria-hidden />
              Текст на всех слайдах — рекомендуемого размера
            </p>
          )}
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Отмена
          </Button>
          <Button type="submit" form="export-form" disabled={busy || !fileName.trim()}>
            {busy ? <Loader2 className="animate-spin" /> : <Download />}
            {busy ? 'Готовим файл…' : 'Скачать PPTX'}
          </Button>
        </DialogFooter>
        </>
        )}
      </DialogContent>
    </Dialog>
  )
}
