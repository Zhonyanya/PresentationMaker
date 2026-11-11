import { useEffect, useMemo, useRef, useState } from 'react'
import { toApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import type { Presentation } from '@/domain/presentation'
import { ExportDialog } from '@/features/editor/ExportDialog'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { buildPresentationScenes } from '@/layouts/registry'
import { importDocxPresentation } from '@/lib/docx-presentation'
import { FileImportError } from '@/lib/file-import'
import { presentationTheme } from '@/theme/presentation-theme'

export function DocumentImportPanel({ preview }: {
  preview: (file: File, signal: AbortSignal) => Promise<Presentation>
}) {
  const [document, setDocument] = useState<Presentation | null>(null)
  const [selected, setSelected] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [warnings, setWarnings] = useState<string[]>([])
  const [exportOpen, setExportOpen] = useState(false)
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])
  const scenes = useMemo(
    () => document ? buildPresentationScenes(document.slides, presentationTheme) : [],
    [document],
  )

  async function importDocument(file: File) {
    const docx = file.name.toLowerCase().endsWith('.docx')
    if (!docx && file.size > 10_000_000) {
      setError('PDF больше 10 МБ.')
      return
    }
    const controller = new AbortController()
    active.current = controller
    setError('')
    setWarnings([])
    setBusy(true)
    try {
      const result = docx
        ? await importDocxPresentation(file)
        : { presentation: await preview(file, controller.signal), warnings: [] }
      if (controller.signal.aborted) return
      setSelected(0)
      setDocument(result.presentation)
      setWarnings(result.warnings)
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(cause instanceof FileImportError ? cause.message : toApiError(cause).message)
      }
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <label className="block font-medium">
        Импорт доклада из PDF или DOCX
        <input
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={busy}
          className="mt-2 block w-full text-sm"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) void importDocument(file)
          }}
        />
      </label>
      {busy && <p role="status">Обрабатываем доклад…</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {warnings.length > 0 && <ul role="status" className="text-sm">{warnings.map((warning) => (
        <li key={warning}>{warning}</li>
      ))}</ul>}
      {document && (
        <>
          <label className="flex items-center gap-2">
            Слайд
            <select value={selected} onChange={(event) => setSelected(Number(event.target.value))}>
              {document.slides.map((slide, index) => (
                <option key={slide.id} value={index}>{index + 1}. {slide.title}</option>
              ))}
            </select>
          </label>
          <div className="overflow-x-auto">
            <SlideRenderer scene={scenes[selected]} scale={640 / SLIDE_PX.width} />
          </div>
          <Button onClick={() => setExportOpen(true)}>Скачать PPTX</Button>
          <ExportDialog open={exportOpen} onOpenChange={setExportOpen} presentation={document} scenes={scenes} />
        </>
      )}
    </section>
  )
}
