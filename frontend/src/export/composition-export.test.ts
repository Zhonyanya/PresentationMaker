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
import { resolvePresentationTheme } from '@/theme/theme-presets'
import { buildPptx } from './pptx-export'

it('сохраняет длинные абзацы в порядке чтения и использует две колонки, когда они помещаются', async () => {
  const paragraphs = [
    'Рабочая группа сверила все исходные журналы и сопоставила записи с выгрузкой за оба периода, после чего отдельно проверила спорные случаи с изменившимися идентификаторами и отметила, какие строки пришлось исключить из сопоставления.',
    'Участников без согласованной даты учитывали отдельно. Пропуски в журналах не заменяли средними значениями.',
    'Смена формы регистрации повлияла на сравнимость результатов. Дополнительную проверку запланировали на июнь.',
    'Данные о причинах исключения доступны в исходной таблице. Для них сохранены прежние коды.',
  ]
  const deck = presentationSchema.parse({
    title: 'Пилот', slides: [{
      id: 'long-evidence', layout: 'text', title: 'Как сверяли данные', body: paragraphs.join('\n\n'),
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const columns = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(columns).toHaveLength(2)
  expect(columns.flatMap(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual(paragraphs)
  expect(columns.every(({ overflow, style }) => !overflow && style.fontSize >= 16)).toBe(true)
  expect(columns[0].box.x + columns[0].box.w).toBeLessThan(columns[1].box.x)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  expect(paragraphs.every((paragraph) => xml.includes(paragraph))).toBe(true)
})

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

it('использует единую точность для целых и дробных процентов в PowerPoint', async () => {
  const deck = presentationSchema.parse({
    title: 'Обучение', slides: [{
      id: 'precision', layout: 'text', title: 'Дистанционные технологии', body: '',
      composition: { kind: 'comparison', unit: '%', categories: ['Магистратура'],
        series: [{ label: '2023', values: [48.3] }, { label: '2024', values: [50] }] },
    }],
  })
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const [file] = zip.file(/^ppt\/charts\/chart\d+\.xml$/)
  const chart = await file.async('string')
  expect(chart).toContain('formatCode="0.0&quot;%&quot;"')
  expect(chart).toContain('<c:v>50</c:v>')
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

it('размещает подписанные годы и базы сравнения рядом, сохраняя знаки изменения', () => {
  const lines = ['2025: 841 поездка, 5 605 миль.', 'К 2024: −9% поездок.', 'К 2019: −12% поездок.']
  const deck = presentationSchema.parse({
    title: 'Поездки',
    slides: [{ id: 'periods', layout: 'text', title: 'Динамика', body: lines.join(' ') }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const groups = scene.elements.filter((element): element is SceneText =>
    element.type === 'text' && element.field === 'body',
  )
  expect(groups.map(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual(lines.map((line) => [line]))
  expect(new Set(groups.map(({ box }) => box.y)).size).toBe(1)
  expect(groups[1].paragraphs[0].emphasis).toContainEqual({ start: 8, end: 11 })
})

it('выделяет числа в явно подписанных группах и сохраняет утверждения целиком', async () => {
  const methods = 'Доля поездок: автомобиль 58% (76% миль), пешком 29%.'
  const purposes = 'Основные цели: покупки 17%, поездки на работу 13%, прогулка 9%.'
  const limit = 'При сравнении учитывали изменение способа регистрации.'
  const deck = presentationSchema.parse({
    title: 'Поездки', slides: [{
      id: 'travel', layout: 'text', title: 'Как и зачем ездили', body: [methods, purposes, limit].join(' '),
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const panels = scene.elements.filter((element): element is SceneText =>
    element.type === 'text' && element.field === 'body',
  )
  expect(panels.map(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual([
    [methods], [purposes], [limit],
  ])
  expect(panels[0].box.y).toBe(panels[1].box.y)
  expect(panels[1].box.x).toBeGreaterThan(panels[0].box.x + panels[0].box.w)
  expect(panels[2].box.y).toBeGreaterThan(panels[1].box.y + panels[1].box.h)
  const preview = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(preview).toMatch(/<strong[^>]*>58%<\/strong>/)
  expect(preview).toMatch(/<strong[^>]*>76%<\/strong>/)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  const paragraphs = [...xml.matchAll(/<a:p(?:\s[^>]*)?>([\s\S]*?)<\/a:p>/g)]
    .map(([paragraph]) => [...paragraph.matchAll(/<a:t(?:\s[^>]*)?>([^<]*)<\/a:t>/g)]
      .map(([, text]) => text).join(''))
  expect(paragraphs).toEqual(expect.arrayContaining([methods, purposes, limit]))
  expect(xml).toMatch(/<a:r><a:rPr[^>]* b="1"[^>]*>[\s\S]*?<\/a:rPr><a:t>58%<\/a:t><\/a:r>/)
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

it('оставляет место под длинные названия групп в компактной диаграмме', async () => {
  const categories = [
    'Северные горные площадки', 'Курганские сельские школы', 'Южные учебные многоцентры',
    'Новые школьные мастерские', 'Дневные районные классы', 'Летние языковые площадки',
  ]
  const body = 'В трёх группах результат снизился, несмотря на расширение охвата в остальных. '
    + 'Данные не корректировали на число смен и длительность занятий, поэтому сравнение описывает '
    + 'только итоговые значения. На школьных площадках применяли одинаковый порядок учёта. '
    + 'В учебных центрах отдельные наблюдения были недоступны, поэтому разные форматы работы имеют '
    + 'несопоставимые условия.'
  const deck = presentationSchema.parse({
    title: 'Охват',
    slides: [{
      id: 'wrap', layout: 'text', title: 'Названия групп', body,
      composition: { kind: 'comparison', categories, series: [
        { label: '2024', values: [19, 23, 56, 17, 21, 19] },
        { label: '2025', values: [21, 24, 54, 16, 20, 23] },
      ] },
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const chart = scene.elements.find((element) => element.type === 'chart')
  expect(chart?.categories).toEqual(categories)
  const plot = chart!.plot
  expect(plot.y * chart!.box.h).toBeGreaterThanOrEqual(0.62)
  expect(plot.y + plot.h).toBeLessThan(0.82)
  const context = scene.elements.find((element) => element.type === 'text' && element.field === 'body')
  expect(context!.box.y).toBeGreaterThan(chart!.box.y + chart!.box.h)
  const preview = renderToStaticMarkup(createElement(SlideRenderer, { scene, scale: 1 }))
  expect(preview).toContain(`height:${plot.h * 100}%`)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const [chartFile] = zip.file(/^ppt\/charts\/chart\d+\.xml$/)
  const chartXml = await chartFile.async('string')
  expect(categories.every((name) => chartXml.includes(name))).toBe(true)
  expect(chartXml).not.toContain('<c:max ')
  const exportedPlotTop = chartXml.match(/<c:y val="([^"]+)"\s*\/>/)?.[1]
  expect(Number(exportedPlotTop)).toBeCloseTo(plot.y)
  const exportedPlotHeight = chartXml.match(/<c:h val="([^"]+)"\s*\/>/)?.[1]
  expect(Number(exportedPlotHeight)).toBeCloseTo(plot.h)
})

it('отдаёт длинному пояснению больше ширины рядом с таблицей сравнения', async () => {
  const categories = [
    'Средние горные школы', 'Региональные училища', 'Лесные учебные центры',
    'Кружки робототехники', 'Дистанционные группы', 'Сельские языковые клубы',
  ]
  const body = [
    'В двух группах результат снизился, несмотря на расширение охвата в остальных. ' +
      'Данные не корректировали на число смен и длительность занятий, поэтому сравнение описывает только итоговые значения.',
    'На школьных площадках применяли одинаковый порядок учёта. ' +
      'В учебных центрах отдельные наблюдения были недоступны, поэтому разные форматы работы имеют несопоставимые условия.',
    'Данные относятся к двум календарным периодам. ' +
      'Изменения в составе групп учитывали отдельно, а выводы о причинах изменений по этому сравнительному ряду не делали.',
  ].join('\n')
  const deck = presentationSchema.parse({
    title: 'Охват', slides: [{
      id: 'explanation', layout: 'text', title: 'Сопоставимость результатов', body,
      composition: { kind: 'comparison', categories, series: [
        { label: '2024', values: [38, 47, 25, 33, 56, 31] },
        { label: '2025', values: [44, 45, 29, 42, 49, 37] },
      ] },
    }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const table = scene.elements.find((element) => element.type === 'table')
  const explanation = scene.elements.find((element): element is SceneText => (
    element.type === 'text' && element.field === 'body'
  ))
  expect(table?.rows.slice(1).map(([name]) => name)).toEqual(categories)
  expect(table!.box.y + table!.box.h).toBeLessThanOrEqual(presentationTheme.spacing.contentBottom)
  expect(explanation!.box.x).toBeGreaterThan(table!.box.x + table!.box.w)
  expect(explanation).toMatchObject({ overflow: false })
  expect(explanation!.style.fontSize).toBeGreaterThanOrEqual(16)
  expect(explanation?.paragraphs.map(({ text }) => text)).toEqual(body.split('\n'))
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const slideXml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  expect(slideXml).toContain('<a:tbl>')
  expect(slideXml).toContain('<a:t>56</a:t>')
  expect(body.split('\n').every((paragraph) => slideXml.includes(paragraph))).toBe(true)
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

it('различает соседние текстовые слайды и сохраняет каждую формулировку в PPTX', async () => {
  const lead = 'Главное условие.'
  const details = 'Подробности указаны в заявке.'
  const wideLead = 'Подтверждение согласия от получателя обычно оформляется отдельной записью в личном кабинете после направления запроса.'
  const document = presentationSchema.parse({
    title: 'Архив',
    slides: ['Запись', 'Выдача', 'Адрес', 'Согласие', 'Подтверждение'].map((title, index) => ({
      id: title, layout: 'text', title, body: (index >= 3 ? wideLead : lead) + ' ' + details,
    })),
  })
  const scenes = buildPresentationScenes(document.slides, presentationTheme)
  const bodyElements = scenes.map((scene) =>
    scene.elements.flatMap((item) => item.type === 'text' && item.field === 'body' ? [item] : []))
  const backgrounds = scenes.map((scene) =>
    scene.elements.some((item) => item.type === 'rect' && item.fill === presentationTheme.colors.primary
      && item.box.h > 1))
  expect(backgrounds).toEqual([true, true, false, true, false])
  expect(bodyElements[0][0].box.w).toBeGreaterThan(bodyElements[1][0].box.w)
  expect(bodyElements[2][0].style.color).toBe(presentationTheme.colors.primary)
  expect(bodyElements.flat().every((item) => !item.overflow)).toBe(true)

  const pptx = await buildPptx(document)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  for (const [index, parts] of bodyElements.entries()) {
    const expected = [index >= 3 ? wideLead : lead, details]
    expect(parts.flatMap((part) => part.paragraphs.map(({ text }) => text))).toEqual(expected)
    const xml = await zip.file(`ppt/slides/slide${index + 1}.xml`)?.async('string') ?? ''
    const text = [...xml.matchAll(/<a:t>(.*?)<\/a:t>/g)].map((match) => match[1])
    expect(text.filter((value) => expected.includes(value))).toEqual(expected)
  }
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


it.each([undefined, { name: 'Тема', primary: '#663366', accent: '#CC4422' }])(
  'применяет шаблон УрФУ к превью и PPTX с брендбуком %j', async (brandbook) => {
  const deck = presentationSchema.parse({
    title: 'Отчёт', themeId: 'urfu', brandbook, slides: [
      { id: 'cover', layout: 'title', title: 'Отчёт' },
      { id: 'body', layout: 'text', title: 'Наблюдения', body: 'Сводка наблюдений за период.' },
      { id: 'end', layout: 'closing', title: 'Результаты' },
    ],
  })
  const preview = renderToStaticMarkup(createElement(function Preview() {
    const scenes = usePresentationScenes(deck.slides, deck.themeId, deck.brandbook)
    return createElement('div', null, ...scenes.map((scene, key) =>
      createElement(SlideRenderer, { scene, key, scale: 1 })))
  }))
  expect(preview.match(/background-image:url/g)).toHaveLength(3)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  for (const index of [1, 2, 3]) {
    const xml = await zip.file(`ppt/slides/slide${index}.xml`)?.async('string') ?? ''
    expect(xml).toMatch(/<p:bg>.*?<a:blipFill[ >]/s)
    if (index === 1) {
      expect(xml).toContain('FCEC4F')
      expect(xml).toContain('typeface="Montserrat"')
      expect(xml).toContain('val="FFFFFF"')
      expect(xml).not.toContain('663366')
    }
  }
  expect(await zip.file('ppt/slides/slide2.xml')?.async('string')).toContain('Сводка наблюдений за период.')
})


it('выделяет подписанные проценты и оставляет условия сравнения на слайде', async () => {
  const description = 'The most common trip purposes in 2025 were'
  const condition = 'These three have been the most popular purposes in each of the past five years.'
  const deck = presentationSchema.parse({ title: 'Travel', slides: [{
    id: 'reasons', layout: 'text', title: 'Why people travelled',
    body: description + " shopping (17%), commuting (13%), and 'just walk' (9%). " + condition,
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const texts = scene.elements.flatMap((element) =>
    element.type === 'text' && element.field === 'body' ? [element] : [])
  const metrics = texts.filter((element) => element.paragraphs.some(({ text }) => /^\d+%$/.test(text)))
  expect(metrics.map((element) => element.paragraphs[0].text)).toEqual(['17%', '13%', '9%'])
  expect(metrics.every((element) => element.style.fontSize >= 29 && !element.overflow)).toBe(true)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({outputType: 'nodebuffer'}) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')?.async('string') ?? ''
  for (const text of [description, 'shopping', 'commuting', 'just walk', '17%', '13%', '9%', condition]) {
    expect(xml).toContain(text)
  }
})

it('balances two dense statements across columns and preserves the lead when more details follow', () => {
  const first = 'Children aged five to ten made almost half of their journeys to school on foot during the last survey year, with the car a close second.'
  const second = 'For children aged eleven to sixteen, walking was also the most common mode, followed by trips by car and journeys on local buses.'
  const third = 'The share of school journeys made by bus was higher among older children.'
  const slides = [
    { id: 'parallel', layout: 'text' as const, title: 'School journeys', body: first + ' ' + second },
    { id: 'lead', layout: 'text' as const, title: 'Travel context', body: first + ' ' + second + ' ' + third },
  ]
  const scenes = buildPresentationScenes(slides, presentationTheme)
  const body = scenes.map((scene) => scene.elements.flatMap((item) =>
    item.type === 'text' && item.field === 'body' ? [item] : []))
  expect(body[0].map(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual([[first], [second]])
  expect(body[0][1].box.x).toBeGreaterThan(body[0][0].box.x)
  expect(body[1][0].style.bold).toBe(true)
  expect(body.flat().every((item) => !item.overflow)).toBe(true)
})

it('advances from the actual lead placement when side placement cannot fit', () => {
  const body = 'Подтверждение согласия от получателя обычно оформляется отдельной записью в личном кабинете после направления запроса. Затем заявка поступает на проверку.'
  const slides = Array.from({ length: 3 }, (_, index) => ({
    id: String(index), layout: 'text' as const, title: 'Подтверждение заявки', body,
  }))
  const scenes = buildPresentationScenes(slides, presentationTheme)
  const highlights = scenes.map(({ elements }) => elements.some((element) =>
    element.type === 'rect' && element.fill === presentationTheme.colors.primary && element.box.h > 1))
  expect(highlights).toEqual([true, false, true])
})

it('группирует подписанные измерения и сохраняет оговорку в PPTX', async () => {
  const lead = 'Выдача оборудования ускорилась.'
  const measures = ['Январь — 4,8 часа,', 'февраль — 4,2 часа,', 'март — 3,1 часа.']
  const caveat = 'Учтены только завершённые выдачи.'
  const deck = presentationSchema.parse({
    title: 'Пилот',
    slides: [{ id: 'measures', layout: 'text', textStyle: 'lead', title: 'Выдача',
      body: lead + '\n' + [...measures, caveat].join(' ') }],
  })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const body = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  const expected = [lead, ...measures, caveat]
  expect(body.flatMap(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual(expected)
  expect(body.every(({ overflow }) => !overflow)).toBe(true)
  expect(body[1].box.y).toBe(body[3].box.y)
  expect(body[1].box.x).toBeLessThan(body[3].box.x)
  expect(body[4].box.y).toBeGreaterThan(body[3].box.y)
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  expect(expected.every((text) => xml.includes(text))).toBe(true)
})

it('показывает русские доли с десятичными запятыми отдельными показателями', async () => {
  const intro = 'Электронное обучение в госвузах — более 50% студентов:'
  const detail = 'Дистанционные технологии учитывались отдельно.'
  const deck = presentationSchema.parse({ title: 'Обучение', slides: [{
    id: 'shares', layout: 'text', title: 'Формы обучения',
    body: intro + ' бакалавриат 51,9%, магистратура 53,9%, специалитет 50,4%. ' + detail,
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const text = scene.elements.flatMap((item) =>
    item.type === 'text' && item.field === 'body' ? item.paragraphs.map(({ text }) => text) : [])
  expect(text).toEqual([intro, '51,9%', 'бакалавриат', '53,9%', 'магистратура', '50,4%', 'специалитет', detail])
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  expect(text.every((part) => xml.includes(part))).toBe(true)
})

it('сопоставляет две серии процентов по названиям категорий и экспортирует редактируемые ячейки', async () => {
  const detail = 'Данные собраны по государственным вузам.'
  const deck = presentationSchema.parse({ title: 'Обучение', slides: [{
    id: 'paired-shares', layout: 'text', title: 'Формы обучения',
    body: 'Электронное обучение в госвузах — более 50% студентов: бакалавриат 51,9%, магистратура 53,9%. '
      + 'Дистанционные технологии: магистратура 50%, бакалавриат 48,6%. ' + detail,
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const table = scene.elements.find((item) => item.type === 'table')!
  expect(table.columnWidths[1]).toBeGreaterThan(table.columnWidths[0])
  expect(table).toMatchObject({
    rows: [
      ['Категория', 'Электронное обучение в госвузах — более 50% студентов', 'Дистанционные технологии'],
      ['бакалавриат', '51,9%', '48,6%'],
      ['магистратура', '53,9%', '50%'],
    ],
  })
  const pptx = await buildPptx(deck)
  const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
  const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
  for (const value of ['<a:tbl>', '<a:t>48,6%</a:t>', detail]) expect(xml).toContain(value)
})

it.each([undefined, { name: 'Тема', primary: '#663366', accent: '#CC4422' }])(
  'сохраняет обычное оформление без выбора УрФУ: %j', async (brandbook) => {
    const deck = presentationSchema.parse({ title: 'Отчёт', brandbook, slides: [
      { id: 'cover', layout: 'title', title: 'Отчёт' },
    ] })
    const preview = renderToStaticMarkup(createElement(function Preview() {
      const [scene] = usePresentationScenes(deck.slides, deck.themeId, deck.brandbook)
      return createElement(SlideRenderer, { scene, scale: 1 })
    }))
    expect(preview).not.toContain('background-image:url')
    const pptx = await buildPptx(deck)
    const zip = await JSZip.loadAsync(await pptx.write({ outputType: 'nodebuffer' }) as Buffer)
    const xml = await zip.file('ppt/slides/slide1.xml')!.async('string')
    expect(xml).not.toContain('<a:blipFill')
    if (brandbook) expect(xml).toContain('663366')
  },
)

it('выравнивает короткие числовые показатели и сохраняет единицы и оговорку', () => {
  const caveat = 'Учитывались только завершённые выдачи.'
  const deck = presentationSchema.parse({ title: 'Пилот', slides: [{
    id: 'counts', layout: 'text', title: 'Динамика выдачи',
    body: 'Январь: 48 комплектов. Февраль: 62 комплекта. Март: 71 комплект. ' + caveat,
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const texts = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(texts.map(({ paragraphs }) => paragraphs[0].text)).toEqual([
    '48', 'Январь · комплектов', '62', 'Февраль · комплекта', '71', 'Март · комплект', caveat,
  ])
  expect(new Set([texts[0].box.y, texts[2].box.y, texts[4].box.y]).size).toBe(1)
  expect(texts.every(({ overflow }) => !overflow)).toBe(true)
})

it('отдаёт длинному выводу больше ширины, чем короткой ссылке под диаграммой', () => {
  const takeaway = 'Заочная форма сократилась с 58,3% до 27,5%, а очно-заочная выросла до 49,1% и стала преобладающей среди студентов частных вузов.'
  const deck = presentationSchema.parse({ title: 'Обучение', slides: [{
    id: 'chart-source', layout: 'text', title: 'Формы обучения',
    body: takeaway + '\nИсточник: МСО.',
    composition: { kind: 'comparison', unit: '%',
      categories: ['Очная форма обучения', 'Заочная форма обучения', 'Очно-заочная форма обучения'],
      series: [{ label: '2020', values: [23.8, 58.3, 17.9] }, { label: '2024', values: [23.4, 27.5, 49.1] }],
    },
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const chart = scene.elements.find((item) => item.type === 'chart')!
  const context = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(context).toHaveLength(2)
  expect(context[0].box.w).toBeGreaterThan(context[1].box.w)
  expect(context.every(({ box, overflow }) => box.y >= chart.box.y + chart.box.h && !overflow)).toBe(true)
})

it('раскладывает явный нумерованный список из одного абзаца по карточкам', () => {
  const items = ['1) Подготовка преподавателей.', '2) Доступность обучения.',
    '3) Обновление лабораторий.', '4) Сотрудничество с работодателями.']
  const deck = presentationSchema.parse({ title: 'Программа', slides: [{
    id: 'priorities', layout: 'text', title: 'Задачи программы', body: items.join(' '),
  }] })
  const [scene] = buildPresentationScenes(deck.slides, presentationTheme)
  const cards = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(cards.map(({ paragraphs }) => paragraphs[0].text)).toEqual(items)
  expect(cards[0].box.x).toBeLessThan(cards[1].box.x)
  expect(cards[0].box.y).toBeLessThan(cards[2].box.y)
  expect(cards.every(({ overflow }) => !overflow)).toBe(true)
})

it('оставляет длинное пояснение на всю ширину под компактной таблицей', () => {
  const body = 'Долю участников программы считали отдельно для каждой группы. '
    + 'В выборку вошли только организации, которые подтвердили сведения за оба периода. '
    + 'Организации, которые сменили систему учёта, в сравнение не включались. '
    + 'Данные нельзя переносить на новые площадки, где отчётность ведётся по другим правилам. '
    + 'Сведения об изменениях состава участников собирали отдельно и использовали при проверке результатов. '
    + 'Проверку проводили до публикации итогов и дополнительно сверяли исходные журналы, чтобы устранить расхождения между подразделениями.'
  const deck = presentationSchema.parse({ title: 'Мониторинг', slides: [{
    id: 'dense-context', layout: 'text', title: 'Доли по категориям', body,
    composition: { kind: 'comparison', unit: '%',
      categories: ['Программы бакалавриата', 'Программы специалитета', 'Программы магистратуры'],
      series: [{ label: '2022', values: [47, 49.9, 50.4] }, { label: '2024', values: [51.9, 50.4, 53.9] }],
    },
  }] })
  const theme = resolvePresentationTheme('urfu')
  const [scene] = buildPresentationScenes(deck.slides, theme)
  const table = scene.elements.find((item) => item.type === 'table')
  const copy = scene.elements.find((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(table?.box.w).toBeCloseTo(theme.slide.width - 2 * theme.spacing.marginX)
  expect(copy?.box.y).toBeGreaterThan(table!.box.y + table!.box.h)
  expect(copy?.paragraphs.map(({ text }) => text)).toEqual([body])
  expect(copy?.overflow).toBe(false)
})

it('сохраняет инициалы внутри предложения при разбиении длинного абзаца на колонки', () => {
  const statements = [
    'Рабочая группа сверила документы всех участников и отдельно проверила записи, по которым менялись правила формирования отчёта.',
    'Результаты обсуждались с представителями университета им. Н.Э. Баумана и других образовательных организаций.',
    'Сравнение проводилось только по площадкам с полными данными, а уточнения по новым участникам внесли в отдельный реестр.',
    'Итоговую подборку передали координаторам для повторной проверки, чтобы опубликовать сводку вместе с необходимыми оговорками.',
  ]
  const deck = presentationSchema.parse({ title: 'Отчёт', slides: [{
    id: 'long-summary', title: 'Проверка данных', layout: 'text', body: statements.join(' '),
  }] })
  const [scene] = buildPresentationScenes(deck.slides, resolvePresentationTheme('urfu'))
  const columns = scene.elements.filter((item): item is SceneText => item.type === 'text' && item.field === 'body')
  expect(columns).toHaveLength(2)
  expect(columns.flatMap(({ paragraphs }) => paragraphs.map(({ text }) => text))).toEqual(statements)
  expect(columns.every(({ overflow }) => !overflow)).toBe(true)
})
