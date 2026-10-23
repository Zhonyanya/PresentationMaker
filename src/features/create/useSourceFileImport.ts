import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { FileImportError, readSourceFile } from '@/lib/file-import'
import { LIMITS } from '@/domain/presentation'

/** Загрузка исходного текста из файла с обработкой ошибок. */
export function useSourceFileImport(onText: (text: string, fileName: string) => void) {
  const [loading, setLoading] = useState(false)

  const importFile = useCallback(
    async (file: File) => {
      setLoading(true)
      try {
        const text = (await readSourceFile(file)).trim()
        if (!text) {
          toast.error('В файле нет текста', { description: file.name })
          return
        }
        const clipped = text.slice(0, LIMITS.sourceTextMax)
        onText(clipped, file.name)
        toast.success('Текст загружен', {
          description: clipped.length < text.length ? `${file.name} — текст сокращён до допустимого объёма` : file.name,
        })
      } catch (error) {
        toast.error('Не удалось загрузить файл', {
          description: error instanceof FileImportError ? error.message : 'Попробуйте другой файл или вставьте текст вручную.',
        })
      } finally {
        setLoading(false)
      }
    },
    [onText],
  )

  return { importFile, loading }
}
