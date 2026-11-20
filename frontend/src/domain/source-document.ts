import { z } from 'zod'
import { generateRequestSchema } from './presentation'

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
    z.object({ ...base, kind: z.literal('illustration'), locator: z.string(), caption: z.string().optional() }),
  ])).min(1).max(10_000),
})

export const serverGenerateRequestSchema = z.union([
  generateRequestSchema.omit({ text: true }).extend({
    text: z.never().optional(),
    source: sourceDocumentSchema,
    mode: z.literal('comparisons').optional(),
  }),
  generateRequestSchema.extend({ source: z.never().optional(), mode: z.never().optional() }),
])

export type SourceDocument = z.infer<typeof sourceDocumentSchema>
export type ServerGenerateRequest = z.infer<typeof serverGenerateRequestSchema>

export interface SourceAttachment {
  name: string
  document: SourceDocument
  compare: boolean
}
