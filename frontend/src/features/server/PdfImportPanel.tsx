import { useEffect, useMemo, useRef, useState } from 'react'
import { toApiError } from '@/api/errors'
import { Button } from '@/components/ui/button'
import type { Presentation } from '@/domain/presentation'
import { ExportDialog } from '@/features/editor/ExportDialog'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { buildPresentationScenes } from '@/layouts/registry'
import { presentationTheme } from '@/theme/presentation-theme'

export function PdfImportPanel({ preview }: {
  preview: (file: File, signal: AbortSignal) => Promise<Presentation>
}) {
  const [document, setDocument] = useState<Presentation | null>(null)
  const [selected, setSelected] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [exportOpen, setExportOpen] = useState(false)
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])
  const scenes = useMemo(
    () => document ? buildPresentationScenes(document.slides, presentationTheme) : [],
    [document],
  )

  async function importPdf(file: File) {
    if (file.size > 10_000_000) {
      setError('PDF больше 10 МБ.')
      return
    }
    const controller = new AbortController()
    active.current = controller
    setError('')
    setBusy(true)
    try {
      const result = await preview(file, controller.signal)
      if (controller.signal.aborted) return
      setSelected(0)
      setDocument(result)
    } catch (cause) {
      if (!controller.signal.aborted) setError(toApiError(cause).message)
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <label className="block font-medium">
        Импорт доклада из PDF
        <input
          type="file"
          accept=".pdf,application/pdf"
          disabled={busy}
          className="mt-2 block w-full text-sm"
          onChange={(event) => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file) void importPdf(file)
          }}
        />
      </label>
      {busy && <p role="status">Обрабатываем страницы доклада…</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
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
