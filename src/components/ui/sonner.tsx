import { Toaster as Sonner, type ToasterProps } from 'sonner'

function Toaster(props: ToasterProps) {
  return (
    <Sonner
      position="bottom-center"
      closeButton
      toastOptions={{
        classNames: {
          toast: 'font-sans !rounded-[4px] !border-border !shadow-[0_18px_40px_-18px_rgb(20_20_20/0.35)] !text-[13px]',
          description: '!text-muted-foreground',
          actionButton: '!bg-primary !text-primary-foreground !rounded-[2px] !font-medium',
        },
      }}
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
