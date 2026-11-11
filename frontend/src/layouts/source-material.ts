import type { Box, SceneTable } from './scene'
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

export function sourceTable(rows: string[][], box: Box, fontFace: string, minSize: number): SceneTable {
  const padding = 4 // pt
  const cellWidth = box.w / rows[0].length - 2 * padding / 72
  let fontSize = 14
  const measureRows = () => rows.map((row) => {
    const textHeight = Math.max(...row.map((text) => estimateTextHeight(
      [{ text }], cellWidth, fontSize, { lineSpacing: 1, paragraphSpacing: 0 },
    )))
    return textHeight + 2 * padding / 72
  })
  let rowHeights = measureRows()
  let height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
  while (height > box.h && fontSize > minSize) {
    fontSize = Math.max(minSize, fontSize - 1)
    rowHeights = measureRows()
    height = rowHeights.reduce((sum, rowHeight) => sum + rowHeight, 0)
  }
  return { type: 'table', box: { ...box, h: height }, rows, fontSize, fontFace, padding, rowHeights }
}
