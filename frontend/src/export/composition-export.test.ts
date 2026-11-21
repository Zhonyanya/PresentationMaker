import { expect, it } from 'vitest'
import JSZip from 'jszip'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { convertSlideReport, splitSlide } from '@/domain/operations'
import { presentationSchema } from '@/domain/presentation'
import { SlideRenderer } from '@/features/slides/SlideRenderer'
import { usePresentationScenes } from '@/hooks/usePresentationScenes'
import type { Slide } from '@/domain/presentation'
import { buildPresentationScenes } from '@/layouts/registry'
import { presentationTheme } from '@/theme/presentation-theme'
import { buildPptx } from './pptx-export'

it('отображает и экспортирует сравнение из одного набора данных', async () => {
  const document = presentationSchema.parse({
    title: 'Пилот',
    slides: [{
      id: 'comparison', layout: 'text', title: 'Завершённые занятия', body: 'Пилот',
      composition: {
        kind: 'comparison', categories: ['Северная', 'Южная'],
        series: [{ label: '2024', values: [48, 31] }, { label: '2025', values: [63, 46] }],
      },
    }],
  })
  const [scene] = buildPresentationScenes(document.slides, presentationTheme)
  const chart = scene.elements.find((element) => element.type === 'chart')
  expect(chart).toMatchObject({ categories: ['Северная', 'Южная'], series: expect.any(Array) })
  const preview = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(preview).toContain('Северная: 2024 — 48, 2025 — 63')
  const pptx = await buildPptx(document)
  const buffer = await pptx.write({ outputType: 'nodebuffer' }) as Buffer
  const zip = await JSZip.loadAsync(buffer)
  const chartXml = await zip.file('ppt/charts/chart1.xml')?.async('string')
  expect(chartXml).toContain('<c:v>Северная</c:v>')
  expect(chartXml).toContain('<c:v>63</c:v>')
  expect(chartXml).toContain('<c:legend>')
  expect(chartXml).not.toContain('<c:max ')
  expect(Object.keys(zip.files).some((name) => /^ppt\/embeddings\/.*\.xlsx$/.test(name))).toBe(true)
})

it('переносит факты в новый макет и сохраняет композицию на исходном слайде при разделении', () => {
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'metric', layout: 'text', title: 'Ожидание',
      body: 'Электронная форма.\nОжидание по телефону не измерялось.', notes: 'Доклад, стр. 2',
      composition: { kind: 'metric', values: [
        { label: '2024', value: '5 дней' }, { label: '2025', value: '4 дня' },
      ] },
    }],
  })
  const report = convertSlideReport(deck.slides[0], 'bullets')
  expect(report.slide).toMatchObject({ bullets: expect.arrayContaining(['2024 — 5 дней', '2025 — 4 дня']) })
  const split = splitSlide(deck, 'metric')
  expect(split.presentation.slides[0]).toMatchObject({ composition: { kind: 'metric' }, notes: 'Доклад, стр. 2' })
  expect(split.presentation.slides[1]).not.toHaveProperty('composition')
})

it('сохраняет точные значения при смене макета и форматирует мелкие деления оси', () => {
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'small', layout: 'text', title: 'Доли', body: '',
      composition: { kind: 'comparison', categories: ['Онлайн'], series: [
        { label: '2024', values: [0.00001] }, { label: '2025', values: [0.00002] },
      ] },
    }],
  })
  const slide = deck.slides[0]
  expect(convertSlideReport(slide, 'bullets').slide).toMatchObject({
    bullets: ['Онлайн. 2024 — 0,00001, 2025 — 0,00002'],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const preview = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(preview).toContain('0,000005')
})

it('показывает плотные сравнения таблицей и сохраняет точные данные в PPTX', async () => {
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'dense', layout: 'text', title: 'Охват', body: 'Контекст сравнения.',
      composition: { kind: 'comparison',
        categories: Array.from({ length: 6 }, (_, index) => `Площадка ${index + 1}`),
        series: ['2024', '2025'].map((label) => ({ label, values: Array(6).fill(999999999) })),
      },
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  expect(scene.elements.some((element) => element.type === 'chart')).toBe(false)
  expect(scene.elements.find((element) => element.type === 'table')).toMatchObject({
    rows: expect.arrayContaining([['Площадка 1', '999 999 999', '999 999 999']]),
  })
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const slideXml = await zip.file('ppt/slides/slide1.xml')?.async('string')
  expect(slideXml).toContain('<a:tbl>')
  expect(slideXml).toContain('Контекст сравнения.')
})

it('рендерит тезис, равноправные блоки и порядок действий из редактируемого body', async () => {
  const document = presentationSchema.parse({
    title: 'Разные исходники', slides: [
      { id: 'lead', layout: 'text', textStyle: 'lead', title: 'Вывод',
        body: 'Приём заявок открыт.\nПроверка занимает два дня.' },
      { id: 'blocks', layout: 'text', textStyle: 'blocks', title: 'Условия',
        body: 'Студенты подают заявление онлайн.\nСотрудники обращаются в отдел кадров.' },
      { id: 'steps', layout: 'text', textStyle: 'steps', title: 'Порядок',
        body: 'Подать заявку.\nПолучить ответ.\nЗабрать документы.' },
      { id: 'dense', layout: 'text', textStyle: 'blocks', title: 'Подробности',
        body: 'Длинное описание '.repeat(70) + '\nПроверка.' },
    ],
  })
  const scenes = buildPresentationScenes(document.slides, presentationTheme)
  const body = (index: number) => scenes[index].elements.filter(
    (element) => element.type === 'text' && element.field === 'body',
  )
  expect([0, 1, 2, 3].map((index) => body(index).length)).toEqual([2, 2, 3, 1])
  expect(body(0)[0]).toMatchObject({ style: { bold: true }, paragraphs: [{ text: 'Приём заявок открыт.' }] })
  const before = renderToStaticMarkup(createElement(SlideRenderer, { scene: scenes[2], scale: 1 }))
  expect(before).toContain('Забрать документы.')
  const result = await buildPptx(document)
  const zip = await JSZip.loadAsync(await result.write({ outputType: 'nodebuffer' }) as Buffer)
  expect(await zip.file('ppt/slides/slide3.xml')?.async('string')).toContain('Забрать документы.')
})

it('чередует расположение тезиса на соседних текстовых слайдах', () => {
  const document = presentationSchema.parse({
    title: 'Архив',
    slides: ['Запись', 'Выдача', 'Адрес'].map((title) => ({
      id: title, layout: 'text', title, body: 'Главное условие. Подробности указаны в заявке.',
    })),
  })
  const leadWidths = buildPresentationScenes(document.slides, presentationTheme).map(
    (scene) => scene.elements.find((element) => element.type === 'text' && element.field === 'body')?.box.w ?? 0,
  )
  expect(leadWidths[0]).toBeGreaterThan(leadWidths[1])
  expect(leadWidths[2]).toBe(leadWidths[0])
})

it('обновляет сцену редактора при смене макета предыдущего слайда', () => {
  const document = presentationSchema.parse({
    title: 'Архив', slides: [
      { id: 'a', layout: 'text', title: 'Введение', body: 'Запись обязательна.' },
      { id: 'b', layout: 'text', title: 'Правила', body: 'Выдача по записи. Пожалуйста, возьмите паспорт.' },
    ],
  })
  const preview = (slides: Slide[]) => renderToStaticMarkup(createElement(function Preview() {
    const [, scene] = usePresentationScenes(slides)
    return createElement(SlideRenderer, { scene, scale: 1 })
  }))
  const previous = preview(document.slides)
  const updated = preview([
    { id: 'a', layout: 'bullets', title: 'Введение', bullets: ['Запись обязательна.'] },
    document.slides[1],
  ])
  expect(updated).not.toBe(previous)
})
