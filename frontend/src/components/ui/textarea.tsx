import * as React from 'react'
import { cn } from '@/lib/utils'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        'flex field-sizing-content min-h-16 w-full rounded-[3px] border border-input bg-card px-3 py-2 text-sm leading-relaxed transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/80',
        'hover:border-[#a9a191] focus-visible:border-foreground focus-visible:ring-0',
        'aria-invalid:border-destructive aria-invalid:ring-destructive/15 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export { Textarea }
