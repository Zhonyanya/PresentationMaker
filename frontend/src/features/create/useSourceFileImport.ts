import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { FileImportError, readSourceFile } from '@/lib/file-import'
import { LIMITS } from '@/domain/presentation'
import { sanitizeText } from '@/lib/text'

/** Загрузка исходного текста из файла с обработкой ошибок. */
export function useSourceFileImport(value: string, onText: (text: string) => void, onLoading: (loading: boolean) => void) {
  const version = useRef(0)
  // Ручная правка, выбор примера или уход со страницы отменяют результат старого импорта.
  useEffect(() => {
    onLoading(false)
    return () => { version.current++ }
  }, [value, onLoading])

  return async (file: File) => {
    const current = ++version.current
    onLoading(true)
    try {
      const result = await readSourceFile(file)
      const text = result.text.trim()
      if (current !== version.current) return
      if (!text) {
        toast.error('В файле нет текста', { description: file.name })
        return
      }
      const clipped = sanitizeText(text.slice(0, LIMITS.sourceTextMax))
      onText(clipped)
      const details = [file.name]
      if (clipped.length < text.length) details.push('Текст сокращён до допустимого объёма.')
      if (result.pagesWithoutText.length) {
        const pages = result.pagesWithoutText
        const more = pages.length > 8 ? ` и ещё ${pages.length - 8}` : ''
        details.push(`Страницы без извлечённого текста: ${pages.slice(0, 8).join(', ')}${more}. Если это сканы, распознайте их и загрузите файл снова.`)
        toast.warning('PDF загружен частично', { description: details.join(' · '), duration: 10000 })
      } else {
        toast.success('Текст загружен', { description: details.join(' · ') })
      }
    } catch (error) {
      if (current === version.current) {
        toast.error('Не удалось загрузить файл', {
          description: error instanceof FileImportError ? error.message : 'Попробуйте другой файл или вставьте текст вручную.',
        })
      }
    } finally {
      if (current === version.current) onLoading(false)
    }
  }
}
