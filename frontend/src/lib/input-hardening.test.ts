import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'
import { decodeText, FileImportError, readSourceFile } from './file-import'
import { sanitizeText } from './text'
import { fitGenerated } from '@/domain/operations'
import { generateResponseSchema, presentationSchema } from '@/domain/presentation'
import { generateMockPresentation } from '@/api/mock/mock-generator'
import { toFileName } from '@/export/pptx-export'

const bytes = (...values: number[]) => new Uint8Array(values).buffer

describe('импорт файлов', () => {
  it('распознаёт UTF-16 с BOM («Юникод» Блокнота)', () => {
    const utf16 = new Uint8Array([0xff, 0xfe, ...Array.from('Привет', (c) => [c.charCodeAt(0) & 0xff, c.charCodeAt(0) >> 8]).flat()])
    expect(decodeText(utf16.buffer)).toBe('Привет')
  })

  it('отличает Windows-1251 от UTF-8 с законным символом-заменителем', () => {
    expect(decodeText(bytes(0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2))).toBe('Привет')
    expect(decodeText(new TextEncoder().encode('Знак � в тексте').buffer)).toBe('Знак � в тексте')
  })

  it('текст, начинающийся с «PK», — это текст, а не архив', () => {
    expect(decodeText(new TextEncoder().encode('PKI: инфраструктура ключей').buffer)).toBe('PKI: инфраструктура ключей')
  })

  it('не выдаёт ZIP или бинарный файл за текст', () => {
    expect(() => decodeText(bytes(0x50, 0x4b, 0x03, 0x04, 0x14))).toThrow(FileImportError)
    expect(() => decodeText(new Uint8Array(200).buffer)).toThrow(FileImportError)
  })

  it('отклоняет DOCX-«бомбу» до разбора документа', async () => {
    const zip = new JSZip()
    zip.file('word/document.xml', '0'.repeat(31 * 1024 * 1024))
    const blob = await zip.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' })
    // Сжатый файл маленький и проходит проверку размера загрузки
    expect(blob.byteLength).toBeLessThan(1024 * 1024)
    await expect(readSourceFile(new File([blob], 'bomb.docx'))).rejects.toThrow('слишком большой после распаковки')
  })
})

describe('очистка текста', () => {
  it('убирает половинки суррогатных пар, но сохраняет эмодзи', () => {
    expect(sanitizeText('a\ud800b\udc00c 😀')).toBe('abc 😀')
  })

  it('имя файла без невидимых символов, подделывающих расширение', () => {
    expect(toFileName('Отчёт\u202Etxt.exe\u200B')).toBe('Отчётtxt.exe.pptx')
  })
})

describe('демо-генератор и схема', () => {
  it('длинный заголовок из текста не ломает генерацию', () => {
    const heading = `# ${'Муниципальное бюджетное общеобразовательное учреждение '.repeat(5)}`
    const response = fitGenerated(generateMockPresentation({ text: `${heading}\n\n${'Текст доклада. '.repeat(20)}`, slideCount: 5 }))
    expect(generateResponseSchema.safeParse(response).success).toBe(true)
  })

  it('документ с повторяющимися ID слайдов отклоняется', () => {
    const slide = { id: 'same', layout: 'section' as const, title: 'Раздел' }
    expect(presentationSchema.safeParse({ title: 'Т', slides: [slide, slide] }).success).toBe(false)
  })
})
