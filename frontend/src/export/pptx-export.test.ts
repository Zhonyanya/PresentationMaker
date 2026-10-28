import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'
import { samplePresentation } from '@/test/fixtures'
import { buildPptx, toFileName } from './pptx-export'

async function exportToZip(includeNotes = true) {
  const pptx = await buildPptx(samplePresentation(), { includeNotes })
  const buffer = (await pptx.write({ outputType: 'nodebuffer' })) as Buffer
  return JSZip.loadAsync(buffer)
}

const slideXml = (zip: JSZip, n: number) => zip.file(`ppt/slides/slide${n}.xml`)!.async('string')

describe('экспорт в PPTX', () => {
  it('создаёт по слайду на каждый слайд редактора, формат 16:9', async () => {
    const zip = await exportToZip()
    const slides = Object.keys(zip.files).filter((f) => /^ppt\/slides\/slide\d+\.xml$/.test(f))
    expect(slides).toHaveLength(6)
    const presentationXml = await zip.file('ppt/presentation.xml')!.async('string')
    // 13.333″ × 7.5″ в EMU
    expect(presentationXml).toMatch(/<p:sldSz cx="1219\d{4}" cy="6858000"/)
  })

  it('текст — редактируемые текстовые поля, не картинки', async () => {
    const zip = await exportToZip()
    const xml = await slideXml(zip, 4)
    expect(xml).toContain('<a:t>Достижения</a:t>')
    expect(xml).toContain('<a:t>Четвёртое</a:t>')
    expect(xml).toContain('<p:txBody>')
    expect(xml).toContain('<a:buChar') // маркеры списка
    // Ни одного изображения: слайды не растеризуются
    expect(Object.values(zip.files).some((f) => f.name.startsWith('ppt/media/') && !f.dir)).toBe(false)
  })

  it('все макеты попадают в файл со своим текстом', async () => {
    const zip = await exportToZip()
    const expected = ['Москва · 2026', 'Результаты', 'Второй абзац.', 'Третье', 'Целевое обучение', 'Спасибо за внимание']
    for (const [i, text] of expected.entries()) expect(await slideXml(zip, i + 1)).toContain(text)
  })

  it('применяет цвета и шрифт темы', async () => {
    const zip = await exportToZip()
    const xml = await slideXml(zip, 1)
    expect(xml).toContain('1F3A5F') // фон титульного
    expect(xml).toContain('typeface="Arial"')
  })

  it('заметки докладчика — по выбору', async () => {
    const withNotes = await exportToZip(true)
    const notes = await Promise.all(Object.keys(withNotes.files).filter((f) => /notesSlide\d+\.xml$/.test(f)).map((f) => withNotes.file(f)!.async('string')))
    expect(notes.some((xml) => xml.includes('Заметка к тексту'))).toBe(true)

    const withoutNotes = await exportToZip(false)
    const notes2 = await Promise.all(Object.keys(withoutNotes.files).filter((f) => /notesSlide\d+\.xml$/.test(f)).map((f) => withoutNotes.file(f)!.async('string')))
    expect(notes2.some((xml) => xml.includes('Заметка к тексту'))).toBe(false)
  })

  it('формирует безопасное имя файла', () => {
    expect(toFileName('Итоги 2025/2026: год')).toBe('Итоги 2025 2026 год.pptx')
    expect(toFileName('   ')).toBe('Презентация.pptx')
  })

  it('удаляет управляющие символы, которые ломают XML (вставка из Word/PDF)', async () => {
    const presentation = samplePresentation()
    presentation.slides[3] = { ...presentation.slides[3], bullets: ['Мягкий\u000bперенос', 'Символ\u0001внутри'], notes: 'Заметка\u000cстраница' } as never
    const pptx = await buildPptx(presentation)
    const zip = await JSZip.loadAsync((await pptx.write({ outputType: 'nodebuffer' })) as Buffer)
    const files = await Promise.all(Object.keys(zip.files).filter((f) => f.endsWith('.xml')).map((f) => zip.file(f)!.async('string')))
    for (const xml of files) expect(xml).not.toMatch(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/)
    expect(await slideXml(zip, 4)).toContain('Символвнутри')
  })
})
