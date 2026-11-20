import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FileImportError } from '@/lib/file-import'
import { toApiError } from '@/api/errors'

export function useSourceFileImport(read: (file: File, signal: AbortSignal) => Promise<void>) {
  const [loading, setLoading] = useState(false)

  const active = useRef<AbortController | null>(null)
  useEffect(() => () => active.current?.abort(), [])

  async function importFile(file: File) {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setLoading(true)
    try {
      await read(file, controller.signal)
      if (!controller.signal.aborted) toast.success('Доклад загружен', { description: file.name })
    } catch (error) {
      if (!controller.signal.aborted) {
        toast.error('Не удалось загрузить файл', {
          description: error instanceof FileImportError ? error.message : toApiError(error).message,
        })
      }
    } finally {
      if (active.current === controller && !controller.signal.aborted) {
        active.current = null
        setLoading(false)
      }
    }
  }

  return { importFile, loading }
}
