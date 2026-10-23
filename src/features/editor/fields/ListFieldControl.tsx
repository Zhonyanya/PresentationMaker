import { useEffect, useRef, type KeyboardEvent } from 'react'
import { Plus, X } from 'lucide-react'
import { LIMITS } from '@/domain/presentation'
import { Button } from '@/components/ui/button'
import { AutoTextarea } from './AutoTextarea'

interface ListFieldControlProps {
  fieldKey: string
  label: string
  placeholder: string
  addLabel: string
  items: string[]
  onChange: (items: string[]) => void
  onFocusField: (key: string | null) => void
}

export function ListFieldControl({ fieldKey, label, placeholder, addLabel, items, onChange, onFocusField }: ListFieldControlProps) {
  const refs = useRef<(HTMLTextAreaElement | null)[]>([])
  const pendingFocus = useRef<{ index: number; caret: 'start' | 'end' } | null>(null)
  const canAdd = items.length < LIMITS.listItemsMax

  useEffect(() => {
    const pending = pendingFocus.current
    if (!pending) return
    const node = refs.current[pending.index]
    if (node) {
      node.focus()
      const pos = pending.caret === 'end' ? node.value.length : 0
      node.setSelectionRange(pos, pos)
    }
    pendingFocus.current = null
  })

  const update = (index: number, value: string) => onChange(items.map((item, i) => (i === index ? value : item)))
  /** Вставка нового пункта; head — новое значение текущего пункта (при разрыве строки по Enter) */
  const insertAfter = (index: number, value = '', head?: string) => {
    if (!canAdd) return
    const next = [...items]
    if (head !== undefined) next[index] = head
    next.splice(index + 1, 0, value)
    pendingFocus.current = { index: index + 1, caret: 'start' }
    onChange(next)
  }
  const remove = (index: number, focusPrevious = false) => {
    const next = items.filter((_, i) => i !== index)
    if (next.length) pendingFocus.current = { index: Math.max(0, focusPrevious ? index - 1 : Math.min(index, next.length - 1)), caret: 'end' }
    onChange(next)
  }
  const move = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= items.length) return
    const next = [...items]
    const [item] = next.splice(index, 1)
    next.splice(target, 0, item)
    pendingFocus.current = { index: target, caret: 'end' }
    onChange(next)
  }

  const onKeyDown = (index: number) => (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const node = event.currentTarget
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      // Перенос хвоста строки в новый пункт, как в текстовых редакторах
      // Одним изменением: два последовательных onChange затёрли бы друг друга
      const tail = node.value.slice(node.selectionEnd).trimStart()
      if (tail) insertAfter(index, tail, node.value.slice(0, node.selectionStart).trimEnd())
      else insertAfter(index)
    } else if (event.key === 'Backspace' && node.value === '' && items.length > 0) {
      event.preventDefault()
      remove(index, true)
    } else if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
      event.preventDefault()
      move(index, event.key === 'ArrowUp' ? -1 : 1)
    }
  }

  return (
    <fieldset className="group/list flex flex-col gap-1.5">
      <legend className="mb-1.5 flex w-full items-baseline justify-between text-[12.5px] font-medium">
        <span>{label}</span>
        <span className="text-[11px] font-normal tabular-nums text-muted-foreground">
          {items.length}/{LIMITS.listItemsMax}
        </span>
      </legend>
      {items.length === 0 && <p className="border border-dashed px-3 py-2.5 text-[12.5px] text-muted-foreground">Пунктов пока нет</p>}
      <ul className="flex flex-col gap-1.5">
        {items.map((item, index) => (
          <li key={index} className="group relative flex items-start gap-2">
            <span className="mt-[15px] size-1.5 shrink-0 rounded-full bg-muted-foreground/50" aria-hidden />
            <AutoTextarea
              ref={(node) => {
                refs.current[index] = node
              }}
              id={index === 0 ? `field-${fieldKey}` : undefined}
              value={item}
              placeholder={placeholder}
              maxLength={1000}
              aria-label={`${label}: пункт ${index + 1}`}
              onChange={(e) => update(index, e.target.value)}
              onKeyDown={onKeyDown(index)}
              onFocus={() => onFocusField(fieldKey)}
              onBlur={() => onFocusField(null)}
              className="pr-8"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="absolute top-1 right-1 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 hover:text-destructive"
              aria-label={`Удалить пункт ${index + 1}`}
              onClick={() => remove(index)}
            >
              <X />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex flex-col items-start gap-0.5 pt-0.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="-ml-2 text-muted-foreground hover:text-foreground"
          onClick={() => insertAfter(items.length - 1)}
          disabled={!canAdd}
        >
          <Plus />
          {addLabel}
        </Button>
        {items.length > 0 && (
          <span className="hidden text-[11px] text-muted-foreground group-focus-within/list:block">
            Enter — новый пункт, Backspace в пустом — удалить, Alt+↑↓ — переместить
          </span>
        )}
      </div>
    </fieldset>
  )
}
