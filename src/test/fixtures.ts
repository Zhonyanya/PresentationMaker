import type { Presentation } from '@/domain/presentation'

/** Презентация со всеми макетами — для тестов операций и экспорта. */
export function samplePresentation(): Presentation {
  return {
    title: 'Итоги года',
    slides: [
      { id: 's1', layout: 'title', title: 'Итоги года', subtitle: 'Доклад на коллегии', caption: 'Москва · 2026', notes: '' },
      { id: 's2', layout: 'section', title: 'Результаты', subtitle: 'Что сделано', notes: '' },
      { id: 's3', layout: 'text', title: 'Общие результаты', body: 'Первый абзац.\nВторой абзац.', notes: 'Заметка к тексту' },
      { id: 's4', layout: 'bullets', title: 'Достижения', bullets: ['Первое', 'Второе', 'Третье', 'Четвёртое'], notes: '' },
      { id: 's5', layout: 'two-column', title: 'Проблемы и решения', leftTitle: 'Проблемы', left: ['Дефицит кадров'], rightTitle: 'Решения', right: ['Целевое обучение'], notes: '' },
      { id: 's6', layout: 'closing', title: 'Спасибо за внимание', subtitle: 'Вопросы', notes: '' },
    ],
  }
}
