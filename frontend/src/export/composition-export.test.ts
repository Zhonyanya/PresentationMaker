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
import type { SceneText } from '@/layouts/scene'
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
  const context = scene.elements.find((element) => element.type === 'text' && element.field === 'body')
  expect(context?.box.x).toBeGreaterThan(chart!.box.x + chart!.box.w)
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

it('даёт длинному пояснению всю ширину под диаграммой и сохраняет оговорки при экспорте', async () => {
  const summary = 'Всего по четырём площадкам завершили 169 занятий в 2024 году и 196 в 2025 году, то есть на 27 больше.'
  const details = 'На Северной и Южной площадках число выросло на 15 занятий в каждой. На Центральной оно снизилось на 3, а на Выездной составило 18 в оба года.'
  const caveat = 'Учёт вёлся по занятиям. Число уникальных посетителей не измеряли.'
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'wide', layout: 'text', title: 'Динамика по площадкам',
      body: summary + ' ' + details + '\n' + caveat,
      composition: {
        kind: 'comparison', categories: ['Северная', 'Центральная', 'Южная', 'Выездная'],
        series: [{ label: '2024', values: [48, 72, 31, 18] },
          { label: '2025', values: [63, 69, 46, 18] }],
      },
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const chart = scene.elements.find((element) => element.type === 'chart')
  const context = scene.elements.filter((element): element is SceneText =>
    element.type === 'text' && element.field === 'body',
  )
  expect(chart?.box.w).toBeCloseTo(presentationTheme.slide.width - 2 * presentationTheme.spacing.marginX)
  expect(context.flatMap((element) => element.paragraphs.map(({ text }) => text)))
    .toEqual([summary, details, caveat])
  for (const element of context) {
    expect(element.box.y).toBeGreaterThan(chart!.box.y + chart!.box.h)
    expect(element.box.y + element.box.h).toBeLessThanOrEqual(presentationTheme.spacing.contentBottom + 0.01)
    expect(element.style.fontSize).toBeGreaterThanOrEqual(16)
    expect(element.overflow).toBe(false)
  }
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const [chartFile] = zip.file(/^ppt\/charts\/chart\d+\.xml$/)
  const chartXml = await chartFile?.async('string')
  const slideXml = await zip.file('ppt/slides/slide1.xml')?.async('string')
  expect(chartXml).toContain('<c:v>69</c:v>')
  for (const sentence of [summary, details, caveat]) expect(slideXml).toContain(sentence)
})

it('оставляет длинное утверждение целым, если оно не помещается в колонку', () => {
  const summary = 'В расчёт вошли ' + 'проверенные показатели для площадки, '.repeat(10) + 'с поправкой на возвраты.'
  const caveat = 'Незавершённые заявки исключены.'
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'wide-caption', layout: 'text', title: 'Сравнение', body: summary + ' ' + caveat,
      composition: { kind: 'comparison', categories: ['Северная', 'Южная'], series: [
        { label: '2024', values: [16, 31] }, { label: '2025', values: [24, 46] },
      ] },
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const chart = scene.elements.find((element) => element.type === 'chart')
  const context = scene.elements.find((element): element is SceneText =>
    element.type === 'text' && element.field === 'body',
  )
  expect(context?.box.y).toBeGreaterThan(chart!.box.y + chart!.box.h)
  expect(context).toMatchObject({ paragraphs: [{ text: summary + ' ' + caveat }], overflow: false })
})

it('показывает равноправные периоды рядом и сохраняет ограничение под ними', async () => {
  const march = '500 проверенных, 15 дефектов (3%).'
  const april = '800 проверенных, 16 дефектов (2%).'
  const limitation = 'Схема отбора изменилась. Статистическая значимость не рассчитана.'
  const document = presentationSchema.parse({
    title: 'Упаковка', slides: [{
      id: 'samples', layout: 'text', title: 'Контроль качества',
      body: `Март: ${march} Апрель: ${april} ${limitation}`,
    }],
  })
  const [scene] = buildPresentationScenes(document.slides, presentationTheme)
  const text = scene.elements.filter((item): item is SceneText =>
    item.type === 'text' && item.field === 'body',
  )
  expect(text.map((item) => item.paragraphs.map((paragraph) => paragraph.text))).toEqual([
    ['Март:'], [march], ['Апрель:'], [april], [limitation],
  ])
  expect(text[1].style.fontSize).toBe(text[3].style.fontSize)
  expect(text[0].box.y).toBe(text[2].box.y)
  expect(text[0].box.x).toBeLessThan(text[2].box.x)
  expect(text[4].box.y).toBeGreaterThan(text[3].box.y)
  expect(text.some((item) => item.overflow)).toBe(false)
  const pptx = await buildPptx(document)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')?.async('string')
  for (const phrase of [march, april, limitation]) expect(xml).toContain(phrase)
})

it('раскладывает перечисленные меры на отдельные карточки и сохраняет вложенную оговорку', async () => {
  const measures = [
    'Планирование по расписанию и прошлой неделе;',
    'приготовление партиями (70% заранее; остальное — по ходу);',
    'выбор размера гарнира (−20 руб.);',
    'ежедневное взвешивание по категориям;',
    'пятничная корректировка плана.',
  ]
  const document = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'changes', layout: 'text', title: 'Что изменили', body: measures.join(' '),
    }, {
      id: 'caution', layout: 'text', title: 'Что изменили',
      body: 'Обновили расписание; если резерв исчерпан, подачу останавливают; затем ждут новую партию.',
    }],
  })
  const [overview, caution] = buildPresentationScenes(document.slides, presentationTheme)
  const visibleMeasures = [
    'Планирование по расписанию и прошлой неделе',
    'Приготовление партиями (70% заранее; остальное — по ходу)',
    'Выбор размера гарнира (−20 руб.)',
    'Ежедневное взвешивание по категориям',
    'Пятничная корректировка плана.',
  ]
  const body = (scene: typeof overview) => scene.elements.filter((item): item is SceneText =>
    item.type === 'text' && item.field === 'body',
  )
  const cards = body(overview)
  expect(cards.map((item) => item.paragraphs[0].text)).toEqual(visibleMeasures)
  expect(cards[2].box.y).toBe(cards[0].box.y)
  expect(cards[3].box.y).toBeGreaterThan(cards[0].box.y + cards[0].box.h)
  expect(cards.every((item) => !item.overflow && item.style.fontSize >= 16)).toBe(true)
  expect(body(caution).flatMap((item) => item.paragraphs.map((p) => p.text)))
    .toEqual([document.slides[1].layout === 'text' && document.slides[1].body])
  const pptx = await buildPptx(document)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')?.async('string')
  for (const measure of visibleMeasures) expect(xml).toContain(measure)
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

it('нумерует действия отдельно от условий и сохраняет текст при переполнении', async () => {
  const actions = ['Покажите пропуск.', 'Получите талон.', 'Подойдите к окну.']
  const condition = 'Доступ подтверждает сотрудник.'
  const body = [...actions, '', 'Условия выдачи', condition].join('\n')
  const document = presentationSchema.parse({
    title: 'Архив', slides: [
      { id: 'steps', layout: 'text', title: 'Порядок выдачи', textStyle: 'steps', body },
      { id: 'dense', layout: 'text', title: 'Другой порядок', textStyle: 'steps',
        body: body.replace(condition, condition.repeat(36)) },
    ],
  })
  const [normal, dense] = buildPresentationScenes(document.slides, presentationTheme)
  const numbers = normal.elements.flatMap((item) =>
    item.type === 'text' && item.field === 'stepNumber' ? item.paragraphs.map(({ text }) => text) : [])
  expect(numbers).toEqual(['1', '2', '3'])
  expect(dense.elements.some((item) => item.type === 'text' && item.field === 'stepNumber')).toBe(false)
  const pptx = await buildPptx(document)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  for (const [index, expected] of [[1, condition], [2, condition.repeat(36)]] as const) {
    const xml = await zip.file(`ppt/slides/slide${index}.xml`)?.async('string') ?? ''
    const text = [...xml.matchAll(/<a:t>(.*?)<\/a:t>/g)].map((match) => match[1])
    expect(text.filter((value) => [...actions, 'Условия выдачи', expected].includes(value)))
      .toEqual([...actions, 'Условия выдачи', expected])
  }
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

it('отображает и экспортирует иерархию, сохраняя текст при переполнении', async () => {
  const body = 'Сервисы библиотеки\nЧитальный зал\n  Работа с подлинниками.\n  Выдача дел по заявке.\n'
    + 'Удалённый доступ\n  Поиск в электронном каталоге.\n  Запрос копий.\n'
    + 'Межбиблиотечный обмен\n  Запрос через библиотеку.\n  Выдача в выбранном филиале.'
  const document = presentationSchema.parse({
    title: 'Услуги', slides: [
      { id: 'tree', layout: 'text', textStyle: 'tree', title: 'Каналы обслуживания', body },
      { id: 'dense', layout: 'text', textStyle: 'tree', title: 'Подробности',
        body: body.replace('Работа с подлинниками.', 'Полное описание '.repeat(60).trim()) },
    ],
  })
  const [tree, dense] = buildPresentationScenes(document.slides, presentationTheme)
  const boxes = tree.elements.filter((element) => element.type === 'text' && element.field === 'body')
  expect(boxes).toHaveLength(7)
  expect(boxes[0].box.y).toBeLessThan(boxes[1].box.y)
  expect(boxes[1].box.x).toBeLessThan(boxes[3].box.x)
  expect(tree.elements.filter((element) => element.type === 'rect'
    && element.box.y >= presentationTheme.spacing.contentTop
    && element.box.y < presentationTheme.spacing.contentBottom)).toHaveLength(3)
  expect(dense.elements.filter((element) => element.type === 'text' && element.field === 'body')).toHaveLength(1)
  const pptx = await buildPptx(document)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')?.async('string')
  expect(xml).toContain('<a:t>Работа с подлинниками.</a:t>')
  expect(xml).toContain('<a:t>Запрос копий.</a:t>')
})

it('показывает общий заголовок дерева один раз', () => {
  const document = presentationSchema.parse({
    title: 'Архив', slides: [{
      id: 'access', layout: 'text', title: 'Каналы доступа', textStyle: 'tree',
      body: 'Каналы доступа\nЧитальный зал\n  Подлинники\nУдалённо\n  Копии',
    }],
  })
  const [scene] = buildPresentationScenes(document.slides, presentationTheme)
  const markup = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(markup.match(/Каналы доступа/g)).toHaveLength(1)
})
