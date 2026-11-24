import { z } from 'zod'
import { generateRequestSchema, themeIdSchema } from './presentation'

export const SOURCE_TEXT_MAX = 120_000

const base = {
  id: z.string().min(1).max(128),
  page: z.number().int().min(1).max(250).optional(),
}

export const sourceDocumentSchema = z.object({
  blocks: z.array(z.discriminatedUnion('kind', [
    z.object({ ...base, kind: z.literal('text'), text: z.string() }),
    z.object({
      ...base, kind: z.literal('table'), rows: z.array(z.array(z.string().nullable())),
      number: z.string().optional(), caption: z.string().optional(), comparable: z.boolean().optional(),
    }),
    z.object({
      ...base, kind: z.literal('illustration'), locator: z.string(), caption: z.string().optional(),
      png: z.string().max(120_000).regex(/^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/]+={0,2}$/).optional(),
    }),
  ])).min(1).max(10_000),
})

export const serverGenerateRequestSchema = z.union([
  generateRequestSchema.omit({ text: true }).extend({
    text: z.never().optional(),
    source: sourceDocumentSchema,
    themeId: themeIdSchema.optional(),
    mode: z.literal('comparisons').optional(),
  }),
  generateRequestSchema.extend({ source: z.never().optional(), mode: z.never().optional(), themeId: themeIdSchema.optional() }),
])

export type SourceDocument = z.infer<typeof sourceDocumentSchema>
export type ServerGenerateRequest = z.infer<typeof serverGenerateRequestSchema>

export interface SourceAttachment {
  name: string
  document: SourceDocument
  compare: boolean
}
