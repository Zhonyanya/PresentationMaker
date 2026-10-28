import type { Modifier } from '@dnd-kit/core'

/** Не даёт утащить миниатюру за пределы списка слайдов. */
export const restrictToParent: Modifier = ({ transform, containerNodeRect, draggingNodeRect }) => {
  if (!containerNodeRect || !draggingNodeRect) return transform
  const minX = containerNodeRect.left - draggingNodeRect.left
  const maxX = containerNodeRect.right - draggingNodeRect.right
  const minY = containerNodeRect.top - draggingNodeRect.top
  const maxY = containerNodeRect.bottom - draggingNodeRect.bottom
  return {
    ...transform,
    x: Math.min(Math.max(transform.x, minX), Math.max(maxX, minX)),
    y: Math.min(Math.max(transform.y, minY), Math.max(maxY, minY)),
  }
}
