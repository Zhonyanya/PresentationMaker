import * as React from 'react'
import { cn } from '@/lib/utils'

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        'h-9 w-full min-w-0 rounded-[3px] border border-input bg-card px-3 text-sm transition-[border-color,box-shadow] outline-none placeholder:text-muted-foreground/80',
        'hover:border-[#a9a191] focus-visible:border-foreground focus-visible:ring-0',
        'aria-invalid:border-destructive aria-invalid:ring-destructive/15 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export { Input }
