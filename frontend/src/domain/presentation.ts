import { z } from 'zod'

/**
 * Единый контракт презентации.
 *
 * Эти схемы — источник правды для:
 *  - документа, который возвращает сервер (GET /api/v1/presentations/{id}, см. README и ML_CONTRACT.md);
 *  - состояния редактора;
 *  - превью и экспорта в PPTX.
 *
 * Чтобы добавить новый макет: добавьте схему слайда сюда, в `slideSchema` и
 * `generatedSlideSchema`, опишите макет в src/layouts/registry.ts и согласуйте
 * его с backend и ML (README, «Как добавить новый макет»).
 */

export const LIMITS = {
  sourceTextMin: 100,
  sourceTextMax: 60_000,
  titleMax: 200,
  slideCountMin: 3,
  slideCountMax: 20,
  slideCountDefault: 8,
  listItemsMax: 12,
} as const

const text = (max = 2000) => z.string().max(max)
const optionalText = (max = 2000) => text(max).optional()
const list = z.array(text(1000)).max(LIMITS.listItemsMax)

const slideBase = {
  id: z.string().min(1),
  notes: optionalText(10_000),
}

export const titleSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('title'),
  title: text(LIMITS.titleMax),
  subtitle: optionalText(400),
  /** Строка с местом/датой/докладчиком, например «Москва · 2026» */
  caption: optionalText(200),
})

export const textSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('text'),
  title: text(LIMITS.titleMax),
  body: text(4000),
})

export const bulletsSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('bullets'),
  title: text(LIMITS.titleMax),
  bullets: list,
})

export const twoColumnSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('two-column'),
  title: text(LIMITS.titleMax),
  leftTitle: optionalText(120),
  left: list,
  rightTitle: optionalText(120),
  right: list,
})

export const sectionSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('section'),
  title: text(LIMITS.titleMax),
  subtitle: optionalText(400),
})

export const closingSlideSchema = z.object({
  ...slideBase,
  layout: z.literal('closing'),
  title: text(LIMITS.titleMax),
  subtitle: optionalText(400),
})

export const slideSchema = z.discriminatedUnion('layout', [
  titleSlideSchema,
  textSlideSchema,
  bulletsSlideSchema,
  twoColumnSlideSchema,
  sectionSlideSchema,
  closingSlideSchema,
])

export const presentationSchema = z
  .object({
    title: text(LIMITS.titleMax),
    slides: z.array(slideSchema).min(1).max(60),
  })
  .refine((p) => new Set(p.slides.map((s) => s.id)).size === p.slides.length, { message: 'ID слайдов должны быть уникальными', path: ['slides'] })

export type TitleSlide = z.infer<typeof titleSlideSchema>
export type TextSlide = z.infer<typeof textSlideSchema>
export type BulletsSlide = z.infer<typeof bulletsSlideSchema>
export type TwoColumnSlide = z.infer<typeof twoColumnSlideSchema>
export type SectionSlide = z.infer<typeof sectionSlideSchema>
export type ClosingSlide = z.infer<typeof closingSlideSchema>

export type Slide = z.infer<typeof slideSchema>
export type SlideLayout = Slide['layout']
export type SlideOf<L extends SlideLayout> = Extract<Slide, { layout: L }>
export type Presentation = z.infer<typeof presentationSchema>

export const SLIDE_LAYOUTS = slideSchema.options.map(
  (option) => option.shape.layout.value,
) as SlideLayout[]

/* ------------------------------------------------------------------ */
/* API: запрос и ответ генерации                                       */
/* ------------------------------------------------------------------ */

export const generateRequestSchema = z.object({
  text: z
    .string()
    .trim()
    .min(LIMITS.sourceTextMin, `Добавьте больше текста — минимум ${LIMITS.sourceTextMin} символов`)
    .max(LIMITS.sourceTextMax, `Текст слишком длинный — максимум ${LIMITS.sourceTextMax.toLocaleString('ru-RU')} символов`),
  title: z.string().trim().max(LIMITS.titleMax, `Название — не больше ${LIMITS.titleMax} символов`).optional(),
  slideCount: z.number().int().min(LIMITS.slideCountMin).max(LIMITS.slideCountMax),
})

export type GenerateRequest = z.infer<typeof generateRequestSchema>

/**
 * Ответ бэкенда. От сервера допускаются послабления, которые фронтенд
 * нормализует сам: `id` можно не передавать, списки можно опустить.
 */
const optionalId = { id: z.string().trim().min(1).optional() }

export const generatedSlideSchema = z.discriminatedUnion('layout', [
  titleSlideSchema.extend(optionalId),
  textSlideSchema.extend(optionalId),
  bulletsSlideSchema.extend({ ...optionalId, bullets: list.default([]) }),
  twoColumnSlideSchema.extend({ ...optionalId, left: list.default([]), right: list.default([]) }),
  sectionSlideSchema.extend(optionalId),
  closingSlideSchema.extend(optionalId),
])

export const generateResponseSchema = z.object({
  title: text(LIMITS.titleMax),
  slides: z.array(generatedSlideSchema).min(1).max(60),
})

export type GenerateResponse = z.infer<typeof generateResponseSchema>
