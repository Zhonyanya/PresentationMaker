import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { basename, join } from 'node:path'
import { parseArgs } from 'node:util'
import { presentationSchema } from '@/domain/presentation'
import { buildPptx } from '@/export/pptx-export'
import { auditPresentation } from '@/layouts/layout-audit'
import { presentationTheme } from '@/theme/presentation-theme'

const args = parseArgs({
  options: { output: { type: 'string' }, 'pptx-dir': { type: 'string' } },
  allowPositionals: true,
})
if (!args.values.output || !args.positionals.length) {
  throw new Error('Usage: audit-layout.ts --output <report.json> [--pptx-dir <dir>] <deck.json>...')
}

const pptxDir = args.values['pptx-dir']
const names = args.positionals.map((path) => basename(path).replace(/\.json$/i, ''))
if (new Set(names.map((name) => name.toLowerCase())).size !== names.length) {
  throw new Error('Use distinct JSON filenames for each presentation')
}
if (pptxDir) await mkdir(pptxDir, { recursive: true })

const reports = []
for (const [index, path] of args.positionals.entries()) {
  const document = presentationSchema.parse(JSON.parse(await readFile(path, 'utf8')))
  reports.push({ file: basename(path), slides: auditPresentation(document.slides, presentationTheme) })
  if (pptxDir) {
    const pptx = await buildPptx(document, { theme: presentationTheme })
    const bytes = await pptx.write({ outputType: 'nodebuffer', compression: true }) as Buffer
    await writeFile(join(pptxDir, names[index] + '.pptx'), bytes)
  }
}

await writeFile(args.values.output, JSON.stringify(reports, null, 2) + '\n', 'utf8')
