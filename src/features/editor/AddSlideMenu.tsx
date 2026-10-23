import type { ReactNode } from 'react'
import { layoutList } from '@/layouts/registry'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { useSlideActions } from './useSlideActions'

export function AddSlideMenu({ children, afterId, align = 'start' }: { children: ReactNode; afterId?: string | null; align?: 'start' | 'end' }) {
  const { add } = useSlideActions()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>{children}</DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-64">
        <DropdownMenuLabel>Новый слайд после текущего</DropdownMenuLabel>
        {layoutList.map((definition) => {
          const Icon = definition.icon
          return (
            <DropdownMenuItem key={definition.layout} onSelect={() => add(definition.layout, afterId)}>
              <Icon />
              <span className="flex flex-col">
                <span>{definition.label}</span>
                <span className="text-[11.5px] text-muted-foreground">{definition.description}</span>
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
