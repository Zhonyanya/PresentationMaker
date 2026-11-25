import { z } from 'zod'

const color = z.string().regex(/^#[0-9a-fA-F]{6}$/)
// Имя попадает в CSS-строку и в атрибут шрифта в XML PowerPoint.
export const fontFamilySchema = z.string().min(1).max(100).regex(/^[^<>&"'\\\x00-\x1f\x7f\ufffe\uffff]+$/u)

export const brandbookSchema = z.object({
  name: z.string().trim().min(1).max(120),
  primary: color,
  accent: color,
  headingFont: fontFamilySchema.optional(),
  bodyFont: fontFamilySchema.optional(),
})

export type Brandbook = z.infer<typeof brandbookSchema>
