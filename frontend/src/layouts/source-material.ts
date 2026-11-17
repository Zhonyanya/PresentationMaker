import type { Box, SceneTable, TableMerge } from './scene'
import { estimateTextHeight } from './text-fit'

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

export function sourceTable(
  rows: string[][], box: Box, fontFace: string, minSize: number, merges?: TableMerge[],
): SceneTable {
  const padding = 4 // pt
  const columnWidth = box.w / rows[0].length
  const cells = visibleTableCells(rows, merges)
  let fontSize = 14
  const measureRows = () => {
    const heights = rows.map(() => 2 * padding / 72)
    cells.forEach((row, index) => row.forEach((cell) => {
      const textHeight = estimateTextHeight(
        [{ text: cell.text }], columnWidth * cell.colspan - 2 * padding / 72, fontSize,
        { lineSpacing: 1, paragraphSpacing: 0 },
      )
      const height = (textHeight + 2 * padding / 72) / cell.rowspan
      for (let offset = 0; offset < cell.rowspan && index + offset < heights.length; offset += 1) {
        heights[index + offset] = Math.max(heights[index + offset], height)
      }
    }))
    return heights
  }
  let rowHeights = measureRows()
  let height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
  while (height > box.h && fontSize > minSize) {
    fontSize = Math.max(minSize, fontSize - 1)
    rowHeights = measureRows()
    height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
  }
  return { type: 'table', box: { ...box, h: height }, rows, merges, fontSize, fontFace, padding, rowHeights }
}
