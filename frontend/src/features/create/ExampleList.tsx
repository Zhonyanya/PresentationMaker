import { useMemo } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { demoExamples, type DemoExample } from '@/data/demo-examples'
import { formatNumber } from '@/lib/utils'
import { SLIDE_PX, SlideRenderer } from '@/features/slides/SlideRenderer'
import { getShowcase } from './showcase'

const THUMB_WIDTH = 104

export function ExampleList({ onPick }: { onPick: (example: DemoExample) => void }) {
  const { previews } = useMemo(getShowcase, [])
  return (
    <ul className="flex flex-col border-t border-border">
      {demoExamples.map((example) => (
        <li key={example.id} className="relative border-b border-border">
          <button
            type="button"
            onClick={() => onPick(example)}
            className="group relative flex w-full items-center gap-4 py-4 text-left outline-none focus-visible:bg-foreground/[0.03]"
          >
            <span className="shrink-0 overflow-hidden shadow-slide ring-1 ring-foreground/10 transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-1 group-hover:-rotate-[2.5deg] group-hover:scale-[1.04] group-focus-visible:-rotate-[2.5deg]">
              <SlideRenderer scene={previews[example.id]} scale={THUMB_WIDTH / SLIDE_PX.width} />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="font-display text-[18px] leading-tight font-[400] tracking-[-0.01em] transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-x-1">{example.label}</span>
              <span className="text-[12.5px] text-muted-foreground">
                {example.kind} · {formatNumber(example.text.length)} знаков
              </span>
            </span>
            <span
              aria-hidden
              className="absolute inset-x-0 -bottom-px h-px origin-left scale-x-0 bg-foreground transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:scale-x-100 group-focus-visible:scale-x-100"
            />
            <ArrowUpRight
              className="size-4 shrink-0 text-muted-foreground transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:rotate-45 group-hover:text-foreground"
              aria-hidden
            />
          </button>
        </li>
      ))}
    </ul>
  )
}
