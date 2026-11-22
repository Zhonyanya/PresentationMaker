import type { Box, SceneTable, TableMerge } from './scene'
import { estimateTextHeight } from './text-fit'
import type { PresentationTheme } from '@/theme/presentation-theme'
import type { TextSlide } from '@/domain/presentation'
import { lines } from './chrome'

type TableMaterial = Extract<NonNullable<TextSlide['sourceMaterial']>, { kind: 'table' }>

export function isComparisonTable(material: TableMaterial): boolean {
  const [heading, first, second] = material.rows[0]
  return heading === 'Группа' && material.rows[0].length === 3 && !material.merges?.length
    && [first, second].every((period) => /^\d{4}$/.test(period))
}

export function comparisonContext(body: string, rowsWithHeader: TableMaterial['rows']) {
  const [[, first, second], ...rows] = rowsWithHeader
  const normalize = (text: string) => text.replace(/\s+/g, ' ').trim()
  const represented = new Set(rows.map(([group, left, right]) => (
    normalize(`${group}. ${first} — ${left}; ${second} — ${right}`)
  )))
  return lines(body).filter(({ text }) => !represented.has(normalize(text)))
}

const PNG_PREFIX = 'data:image/png;base64,'

/** The PNG IHDR stores its pixel dimensions in the first 24 bytes. */
export function sourceImageBox(src: string, box: Box): Box {
  if (!src.startsWith(PNG_PREFIX)) return box
  const encodedHeader = src.slice(PNG_PREFIX.length, PNG_PREFIX.length + 32)
  if (!/^[A-Za-z0-9+/]{32}$/.test(encodedHeader)) return box
  const header = atob(encodedHeader)
  if (header.slice(0, 8) !== '\x89PNG\r\n\x1a\n' || header.slice(12, 16) !== 'IHDR') return box

  const dimensions = new DataView(Uint8Array.from(header, (byte) => byte.charCodeAt(0)).buffer)
  const width = dimensions.getUint32(16)
  const height = dimensions.getUint32(20)
  if (!width || !height) return box
  const scale = Math.min(box.w / width, box.h / height)
  const w = width * scale
  const h = height * scale
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h }
}

export function visibleTableCells(rows: string[][], merges: TableMerge[] = []) {
  return rows.map((row, rowIndex) => row.flatMap((text, column) => {
    const merge = merges.find((span) => span.row <= rowIndex && rowIndex < span.row + span.rowspan
      && span.column <= column && column < span.column + span.colspan)
    if (merge && (merge.row !== rowIndex || merge.column !== column)) return []
    return [{ text, column, rowspan: merge?.rowspan ?? 1, colspan: merge?.colspan ?? 1 }]
  }))
}

export function comparisonTableStyle({ colors }: PresentationTheme): SceneTable['comparisonStyle'] {
  return {
    headerFill: colors.primary,
    headerText: colors.textOnPrimary,
    rowFill: colors.background,
    alternateFill: colors.surface,
    bodyText: colors.text,
  }
}

export function sourceTable(
  rows: string[][], box: Box, fontFace: string, minSize: number, merges?: TableMerge[],
  comparisonStyle?: SceneTable['comparisonStyle'],
): SceneTable {
  const padding = comparisonStyle ? 7 : 4 // pt
  const defaultWidths = comparisonStyle
    ? [box.w * 0.5, box.w * 0.25, box.w * 0.25]
    : rows[0].map(() => box.w / rows[0].length)
  const cells = visibleTableCells(rows, merges)

  const measureRows = (columnWidths: number[], fontSize: number) => {
    const heights = rows.map(() => 2 * padding / 72)
    cells.forEach((row, index) => row.forEach((cell) => {
      const width = columnWidths.slice(cell.column, cell.column + cell.colspan)
        .reduce((sum, column) => sum + column, 0)
      const textHeight = estimateTextHeight(
        [{ text: cell.text }], width - 2 * padding / 72, fontSize,
        { bold: Boolean(comparisonStyle && index === 0), lineSpacing: 1, paragraphSpacing: 0 },
      )
      const height = (textHeight + 2 * padding / 72) / cell.rowspan
      for (let offset = 0; offset < cell.rowspan && index + offset < heights.length; offset += 1) {
        heights[index + offset] = Math.max(heights[index + offset], height)
      }
    }))
    return heights
  }
  const fitColumns = (columnWidths: number[]) => {
    let fontSize = 14
    let rowHeights = measureRows(columnWidths, fontSize)
    let height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
    while (height > box.h && fontSize > minSize) {
      fontSize = Math.max(minSize, fontSize - 1)
      rowHeights = measureRows(columnWidths, fontSize)
      height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
    }
    return { columnWidths, fontSize, rowHeights, height }
  }

  let selected = fitColumns(defaultWidths)
  if (!comparisonStyle && !merges?.length) {
    // Reserve half the width equally. Longer cells compete for the remaining half.
    const weights = rows[0].map((_, column) => Math.sqrt(Math.max(
      1, ...rows.flatMap((row) => (row[column] ?? '').split('\n').map((line) => line.trim().length)),
    )))
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0)
    const minimumWidth = box.w / (2 * weights.length)
    const candidate = fitColumns(weights.map((weight) => minimumWidth + box.w * weight / (2 * totalWeight)))
    if (candidate.fontSize > selected.fontSize
        || (candidate.fontSize === selected.fontSize && candidate.height < selected.height - 0.01)) {
      selected = candidate
    }
  }
  const { columnWidths, fontSize, rowHeights, height } = selected

  return {
    type: 'table', box: { ...box, h: height }, rows, merges, fontSize, fontFace,
    padding, columnWidths, rowHeights, comparisonStyle,
  }
}

export function tableCellStyle(table: SceneTable, row: number, column: number) {
  const style = table.comparisonStyle
  if (!style) return undefined
  return {
    fill: row === 0 ? style.headerFill : row % 2 ? style.rowFill : style.alternateFill,
    color: row === 0 ? style.headerText : style.bodyText,
    bold: row === 0,
    align: column === 0 ? 'left' as const : 'right' as const,
  }
}
