import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { FileImportError } from './file-import'

GlobalWorkerOptions.workerSrc = workerUrl

export async function withPdf<T>(file: File, read: (pdf: PDFDocumentProxy) => Promise<T>): Promise<T> {
  const task = getDocument({ data: await file.arrayBuffer(), isEvalSupported: false, useSystemFonts: true })
  try {
    return await read(await task.promise)
  } catch (error) {
    if (error instanceof FileImportError) throw error
    if (error instanceof Error && error.name === 'PasswordException') {
      throw new FileImportError('PDF защищён паролем. Загрузите копию без пароля.')
    }
    throw new FileImportError('Не удалось прочитать PDF. Проверьте файл или сохраните его заново.')
  } finally {
    await task.destroy()
  }
}

/** Останавливаем чтение у лимита поля, сохраняя переносы строк и границы страниц. */
export async function pdfText(pdf: PDFDocumentProxy, limit: number) {
  let text = ''
  const pagesWithoutText: number[] = []
  for (let number = 1; number <= pdf.numPages && text.length < limit; number++) {
    let pageText = ''
    const page = await pdf.getPage(number)
    const reader = page.streamTextContent().getReader()
    try {
      while (text.length + pageText.length < limit) {
        const { done, value } = await reader.read()
        if (done) break
        for (const item of value.items) {
          if (!('str' in item)) continue
          pageText += item.str.slice(0, limit - text.length - pageText.length) + (item.hasEOL ? '\n' : ' ')
          if (text.length + pageText.length >= limit) break
        }
      }
    } finally {
      await reader.cancel()
      page.cleanup()
    }
    const content = pageText.trim()
    if (content) text += (text ? '\n\n' : '') + content
    else pagesWithoutText.push(number)
  }
  return { text, pagesWithoutText }
}
