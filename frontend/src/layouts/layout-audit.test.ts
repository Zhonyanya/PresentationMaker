import { expect, it } from 'vitest'
import type { Slide } from '@/domain/presentation'
import { sceneHasOverflow } from '@/hooks/usePresentationScenes'
import { presentationTheme } from '@/theme/presentation-theme'
import { auditPresentation } from './layout-audit'
import { buildPresentationScenes } from './registry'

it('checks the same scenes as export and reports overflow by slide and text field', () => {
  const slides: Slide[] = [
    { id: 'title', layout: 'title', title: 'Пилот' },
    { id: 'dense', layout: 'text', title: 'Наблюдения', body: 'Длинная формулировка. '.repeat(180) },
    { id: 'clips', layout: 'text', title: 'Детали', body: 'Один абзац.\n'.repeat(140) },
    { id: 'empty', layout: 'text', title: 'Выводы', body: '   ' },
    { id: 'sparse', layout: 'text', title: 'Критерий', body: 'Условие действует в часы приёма.' },
    { id: 'closing', layout: 'closing', title: 'Спасибо' },
  ]
  const [title, dense, clips, empty, sparse, closing] = auditPresentation(slides, presentationTheme)
  expect(title.contentVerticalCoverage).toBeNull()
  expect(dense.warnings).toContainEqual(expect.objectContaining({
    code: 'reduced-text-size', field: 'body',
  }))
  expect(clips.warnings).toContainEqual(expect.objectContaining({
    code: 'estimated-text-clipping', field: 'body',
  }))
  expect(dense.number).toBe(2)
  expect(empty.warnings).toEqual([{ code: 'empty-content' }])
  expect(empty.contentVerticalCoverage).toBe(0)
  expect(sparse.warnings).toEqual([])
  expect(sparse.contentVerticalCoverage).toBeGreaterThan(0)
  expect(sparse.contentVerticalCoverage).toBeLessThan(0.4)
  expect(closing.contentVerticalCoverage).toBeNull()
})

it('catches tables that intrude on the footer even when the text fits inside each cell', () => {
  const slides: Slide[] = [{
    id: 'table', layout: 'text', title: 'Исходные данные', body: '',
    sourceMaterial: {
      kind: 'table', page: 1, rows: Array.from({ length: 9 }, () => [
        'Длинная строка. '.repeat(17), 'Содержание. '.repeat(20),
      ]),
    },
  }]
  const [slide] = auditPresentation(slides, presentationTheme)
  expect(slide.warnings).toContainEqual(expect.objectContaining({
    code: 'outside-content-band', type: 'table',
  }))
  expect(sceneHasOverflow(buildPresentationScenes(slides, presentationTheme)[0])).toBe(true)
})

it('widens the prose column when uniform widths force a dense source table to shrink', () => {
  const note = 'Заявки с неполными сведениями учитывались отдельно. При сверке итогов даты и подразделения проверяли по исходным журналам.'
  const description = 'Принято в работу в пределах установленного срока и проверено по исходным записям.'
  const rows = [['Группа', 'Описание', 'Объём', 'Срок'], ...Array.from({ length: 6 }, (_, index) => [
    `Группа ${index + 1}`, description, String(index + 7), 'до конца месяца',
  ])]
  const slide: Slide = {
    id: 'table', layout: 'text', title: 'Сводка', body: `1. ${note}\n2. ${note}`,
    sourceMaterial: { kind: 'table', page: 1, rows },
  }
  const [scene] = buildPresentationScenes([slide], presentationTheme)
  const table = scene.elements.find((element) => element.type === 'table')!
  expect(table.columnWidths[1]).toBeGreaterThan(table.columnWidths[2])
  expect(table.columnWidths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(table.box.w)
  expect(table.fontSize).toBeGreaterThanOrEqual(11)
  expect(table.box.y + table.box.h).toBeLessThanOrEqual(presentationTheme.spacing.contentBottom)
  expect(table.rows).toEqual(rows)
})
