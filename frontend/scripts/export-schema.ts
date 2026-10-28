/**
 * Выгружает JSON Schema контракта из Zod-схем — для бэкенда
 * (валидация, structured output у языковой модели).
 * Запуск: npm run schema
 */
import { writeFileSync } from 'node:fs'
import { z } from 'zod'
import { generateRequestSchema, generateResponseSchema } from '../src/domain/presentation'

// Схемы — общий контракт frontend и backend, поэтому лежат в корневом docs/
const docs = new URL('../../docs/', import.meta.url)

const out = (name: string, schema: z.ZodType, io: 'input' | 'output') =>
  writeFileSync(new URL(`${name}.schema.json`, docs), JSON.stringify(z.toJSONSchema(schema, { io }), null, 2) + '\n')

out('generate-request', generateRequestSchema, 'input')
out('generate-response', generateResponseSchema, 'input')
console.log('docs/generate-request.schema.json, docs/generate-response.schema.json')
