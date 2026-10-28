import * as React from 'react'
import { Slot } from 'radix-ui'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[3px] text-[13.5px] font-medium tracking-[-0.005em] transition-[color,background-color,border-color,box-shadow,transform] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] select-none outline-none focus-visible:ring-2 focus-visible:ring-ring/80 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-[#2a2a28]',
        destructive: 'bg-destructive text-white hover:bg-destructive/90',
        outline:
          'border border-[#141414]/25 bg-transparent bg-[linear-gradient(var(--foreground),var(--foreground))] bg-no-repeat bg-[length:0%_100%] bg-left text-foreground transition-[background-size,color,border-color] duration-500 hover:border-foreground hover:bg-[length:100%_100%] hover:text-background',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-[#dfd9cb]',
        ghost: 'text-foreground/75 hover:bg-foreground/[0.05] hover:text-foreground',
        link: 'link-draw h-auto rounded-none px-0 text-foreground',
      },
      size: {
        default: 'h-9 px-4',
        sm: 'h-8 gap-1.5 px-3 text-[13px]',
        lg: 'h-11 px-6 text-[14px]',
        xl: 'h-12 px-7 text-[14.5px]',
        icon: 'size-9',
        'icon-sm': 'size-8',
        'icon-xs': 'size-7',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : 'button'
  return <Comp data-slot="button" className={cn(buttonVariants({ variant, size, className }))} {...props} />
}

export { Button, buttonVariants }
