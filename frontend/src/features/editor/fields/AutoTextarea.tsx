import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, type ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/** Textarea, высота которой подстраивается под текст (работает во всех браузерах). */
export const AutoTextarea = forwardRef<HTMLTextAreaElement, ComponentProps<'textarea'>>(function AutoTextarea(
  { className, value, ...props },
  forwardedRef,
) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useImperativeHandle(forwardedRef, () => ref.current as HTMLTextAreaElement)

  useLayoutEffect(() => {
    const node = ref.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight + 2}px`
  }, [value])

  return (
    <textarea
      ref={ref}
      value={value}
      rows={1}
      className={cn(
        'block w-full resize-none overflow-hidden rounded-[3px] border border-input bg-card px-3 py-2 text-[13.5px] leading-[1.5] outline-none transition-[border-color] duration-300 placeholder:text-muted-foreground/70',
        'hover:border-[#a9a191] focus-visible:border-foreground',
        className,
      )}
      {...props}
    />
  )
})
