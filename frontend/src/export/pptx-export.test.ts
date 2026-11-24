import { describe, expect, it } from 'vitest'
import JSZip from 'jszip'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SlideRenderer } from '@/features/slides/SlideRenderer'
import { buildPresentationScenes } from '@/layouts/registry'
import { samplePresentation } from '@/test/fixtures'
import { presentationTheme } from '@/theme/presentation-theme'
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

it('exports a source table as native PowerPoint cells', async () => {
  const pptx = await buildPptx({
    title: 'Доклад',
    slides: [{
      id: 'table-1', layout: 'text', title: 'Таблица', body: '',
      sourceMaterial: { kind: 'table', page: 8, rows: [['Школа', 'Участники'], ['А', '23']] },
    }],
  })
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  expect(xml).toContain('<a:tbl>')
  expect(xml).toContain('<a:t>Участники</a:t>')
  expect(xml).toContain('<a:t>23</a:t>')
})

it('preserves a table caveat without repeating values already shown in cells', async () => {
  const caveat = 'По телефону время ожидания не измеряли.'
  const duplicated = 'Север. 2024 — 18; 2025 — 21'
  const pptx = await buildPptx({
    title: 'Доклад',
    slides: [{
      id: 'context-with-table', layout: 'text', title: 'Заявки', body: duplicated + '\n' + caveat,
      sourceMaterial: {
        kind: 'table', page: 1, rows: [['Группа', '2024', '2025'], ['Север', '18', '21']],
      },
    }],
  })
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  expect(xml).toContain(caveat)
  expect(xml).toContain('<a:tbl>')
  expect(xml).toContain('<a:t>21</a:t>')
  expect(xml).not.toContain(duplicated)
})

it('gives editable comparison tables a clear header in preview and PowerPoint', async () => {
  const presentation = samplePresentation()
  presentation.slides = [{
    id: 'comparison-table', layout: 'text', title: 'Заявки', body: '',
    sourceMaterial: {
      kind: 'table', page: 1, rows: [['Группа', '2024', '2025'], ['Север', '18', '21']],
    },
  }]
  const [scene] = buildPresentationScenes(presentation.slides, presentationTheme)
  const html = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(html).toContain('<th scope="col"')
  expect(html.toLowerCase()).toContain(presentationTheme.colors.primary.toLowerCase())
  const pptx = await buildPptx(presentation)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  const [heading, dataRow] = xml.match(/<a:tr h="\d+">.*?<\/a:tr>/gs) ?? []
  expect(heading).toContain('<a:srgbClr val="1F3A5F"/>')
  expect(dataRow).toContain('<a:t>21</a:t>')
  const frame = xml.match(/<p:graphicFrame>.*?<\/p:graphicFrame>/s)?.[0] ?? ''
  const frameWidth = Number(frame.match(/<a:ext cx="(\d+)"/)?.[1])
  const columnsWidth = [...frame.matchAll(/<a:gridCol w="(\d+)"/g)]
    .reduce((total, column) => total + Number(column[1]), 0)
  expect(Math.abs(frameWidth - columnsWidth)).toBeLessThanOrEqual(3)
})

it('exports both axes of a merged source cell as an editable PowerPoint grid', async () => {
  const pptx = await buildPptx({
    title: 'Доклад',
    slides: [{
      id: 'merged-table', layout: 'text', title: 'Таблица', body: '',
      sourceMaterial: {
        kind: 'table',
        rows: [['Общий показатель', '', 'Год'], ['', '', '2025'], ['А', 'Б', '2026']],
        merges: [{ row: 0, column: 0, rowspan: 2, colspan: 2 }],
      },
    }],
  })
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  expect(xml.match(/<a:gridCol /g)).toHaveLength(3)
  const rows = [...xml.matchAll(/<a:tr h="\d+">.*?<\/a:tr>/gs)].map(([row]) => row)
  expect(rows).toHaveLength(3)
  for (const row of rows) expect(row.match(/<a:tc[ >]/g)).toHaveLength(3)
  expect(rows[0]).toContain('<a:tc rowSpan="2" gridSpan="2">')
  expect(rows[1]).toContain('vMerge="1" hMerge="1"')
  expect(rows[1]).toContain('<a:t>2025</a:t>')
})

it('preserves the aspect ratio of a portrait PNG crop', async () => {
  const pptx = await buildPptx({
    title: 'Доклад',
    slides: [{
      id: 'image-1', layout: 'text', title: 'Иллюстрация', body: 'Охват вырос на 9 процентных пунктов.',
      sourceMaterial: {
        kind: 'image',
        page: 1,
        // A 1 × 2 PNG.
        png: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAACCAIAAAAW4yFwAAAADElEQVR4nGNggAMAAAgAAf0HtVgAAAAASUVORK5CYII=',
      },
    }],
  })
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  const picture = xml.match(/<p:pic>.*?<\/p:pic>/s)?.[0]
  const [, width, height] = picture?.match(/<a:ext cx="(\d+)" cy="(\d+)"/) ?? []
  expect(Number(width) / Number(height)).toBeCloseTo(0.5)
  expect(Number(height) / 914400).toBeCloseTo(4.65)
  expect(xml).toContain('<a:t>Охват вырос на 9 процентных пунктов.</a:t>')
})

it('allocates more height to rows with multiline PDF cells', async () => {
  const pptx = await buildPptx({
    title: 'Доклад',
    slides: [{
      id: 'table-1', layout: 'text', title: 'Таблица', body: '',
      sourceMaterial: {
        kind: 'table', page: 1,
        rows: [['Показатель', 'Значение'], ['Первая строка\nВторая строка\nТретья строка', '23']],
      },
    }],
  })
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await slideXml(zip, 1)
  const heights = Array.from(xml.matchAll(/<a:tr h="(\d+)"/g), (match) => Number(match[1]))
  expect(heights).toHaveLength(2)
  expect(heights[1]).toBeGreaterThan(heights[0])
  expect(heights[0] + heights[1]).toBeLessThanOrEqual(4.65 * 914400)
})
