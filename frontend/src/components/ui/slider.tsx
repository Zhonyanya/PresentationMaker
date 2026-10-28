import * as React from 'react'
import { Slider as SliderPrimitive } from 'radix-ui'
import { cn } from '@/lib/utils'

function Slider({ className, ...props }: React.ComponentProps<typeof SliderPrimitive.Root>) {
  const count = (props.value ?? props.defaultValue ?? [0]).length
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      className={cn('relative flex w-full touch-none items-center select-none py-2 data-[disabled]:opacity-50', className)}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-px w-full grow bg-[#cbc4b4]">
        <SliderPrimitive.Range className="absolute -top-px h-[3px] bg-foreground" />
      </SliderPrimitive.Track>
      {Array.from({ length: count }, (_, i) => (
        <SliderPrimitive.Thumb
          key={i}
          aria-label={props['aria-label']}
          className="block size-4 shrink-0 rounded-full border border-foreground bg-card transition-transform duration-300 hover:scale-125 focus-visible:ring-2 focus-visible:ring-foreground focus-visible:ring-offset-2 focus-visible:ring-offset-card focus-visible:outline-none active:scale-110"
        />
      ))}
    </SliderPrimitive.Root>
  )
}

export { Slider }
