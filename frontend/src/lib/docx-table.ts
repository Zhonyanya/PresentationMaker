import type { TableMerge } from '@/layouts/scene'
import { sourceTable } from '@/layouts/source-material'
import { presentationTheme } from '@/theme/presentation-theme'
import { sanitizeText } from './text'

interface TablePart {
  rows: string[][]
  merges?: TableMerge[]
}

export function readDocxTableGrid(table: HTMLTableElement): { rows: string[][]; merges: TableMerge[] } | undefined {
  if (table.querySelector('table') || table.rows.length < 2 || table.rows.length > 590) return
  const grid: (string | undefined)[][] = Array.from(table.rows, () => [])
  const merges: TableMerge[] = []
  for (const [row, source] of Array.from(table.rows).entries()) {
    let column = 0
    for (const cell of Array.from(source.cells)) {
      while (grid[row][column] !== undefined) column += 1
      const { rowSpan: rowspan, colSpan: colspan } = cell
      const value = sanitizeText(cell.textContent ?? '').replace(/\s+/g, ' ').trim()
      if (rowspan < 1 || row + rowspan > grid.length || column + colspan > 8 || value.length > 300) return
      for (let r = row; r < row + rowspan; r += 1) {
        for (let c = column; c < column + colspan; c += 1) {
          if (grid[r][c] !== undefined) return
          grid[r][c] = r === row && c === column ? value : ''
        }
      }
      if (rowspan > 1 || colspan > 1) merges.push({ row, column, rowspan, colspan })
      column += colspan
    }
  }
  const columns = grid[0].length
  if (columns < 2 || grid.some((row) => row.length !== columns
    || Array.from(row).some((cell) => cell === undefined))) return
  return { rows: grid as string[][], merges }
}

export function splitDocxTable(table: HTMLTableElement, grid = readDocxTableGrid(table)): TablePart[] {
  if (!grid) return []
  const { rows, merges } = grid
  const { slide, spacing, fonts, typography } = presentationTheme
  const box = { x: 0, y: 0, w: slide.width - 2 * spacing.marginX, h: spacing.contentBottom - spacing.contentTop }
  const fits = (part: TablePart) => part.rows.length >= 2 && part.rows.length <= 10
    && sourceTable(part.rows, box, fonts.body, typography.absoluteMinFontSize, part.merges).box.h <= box.h
  if (fits(grid)) return [grid]

  const firstBodyRow = Array.from(table.rows).findIndex((row) => !row.querySelector('th'))
  if (firstBodyRow === -1 || firstBodyRow >= 10) return []
  const unsafeCuts = new Set<number>()
  for (const { row, rowspan } of merges) {
    for (let cut = row + 1; cut < row + rowspan; cut += 1) unsafeCuts.add(cut)
  }
  if (unsafeCuts.has(firstBodyRow)) return []
  const header = rows.slice(0, firstBodyRow)
  const headerMerges = merges.filter(({ row }) => row < firstBodyRow)

  // Work backwards so a greedy split cannot leave an orphan row or break a merge.
  const nextParts = new Map<number, { end: number; part: TablePart }>()
  for (let start = rows.length - 1; start >= firstBodyRow; start -= 1) {
    if (unsafeCuts.has(start)) continue
    for (let end = Math.min(rows.length, start + 10 - header.length); end > start; end -= 1) {
      if (end !== rows.length && !nextParts.has(end)) continue
      const part = {
        rows: [...header, ...rows.slice(start, end)],
        merges: [...headerMerges, ...merges.filter(({ row }) => row >= start && row < end)
          .map((merge) => ({ ...merge, row: header.length + merge.row - start }))],
      }
      if (fits(part)) {
        nextParts.set(start, { end, part })
        break
      }
    }
  }
  if (!nextParts.has(firstBodyRow)) return []
  const parts: TablePart[] = []
  for (let start = firstBodyRow; start < rows.length;) {
    const next = nextParts.get(start)!
    parts.push(next.part)
    start = next.end
  }
  return parts
}
