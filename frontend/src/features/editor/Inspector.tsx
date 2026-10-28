import { motion } from 'motion/react'
import { Copy, Scissors, Trash2 } from 'lucide-react'
import { EASE_OUT_EXPO } from '@/components/app/motion'
import type { Slide } from '@/domain/presentation'
import { getLayout } from '@/layouts/registry'
import type { FieldDef } from '@/layouts/types'
import { canSplitSlide } from '@/domain/operations'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useEditorStore } from '@/store/editor-store'
import { LayoutPicker } from './LayoutPicker'
import { TextFieldControl } from './fields/TextFieldControl'
import { ListFieldControl } from './fields/ListFieldControl'
import { AutoTextarea } from './fields/AutoTextarea'
import { useSlideActions } from './useSlideActions'

interface InspectorProps {
  slide: Slide
  index: number
  total: number
  onFocusField: (field: string | null) => void
}

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 px-5 py-5">
      <div className="flex items-center justify-between">
        <h3 className="eyebrow">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

export function Inspector({ slide, index, total, onFocusField }: InspectorProps) {
  const updateSlide = useEditorStore((s) => s.updateSlide)
  const { changeLayout, duplicate, remove, split } = useSlideActions()
  const definition = getLayout(slide.layout)
  const fields = definition.fields as FieldDef<Record<string, unknown>>[]
  const values = slide as unknown as Record<string, unknown>

  return (
    <aside aria-label="Настройки слайда" className="flex min-h-0 flex-col border-border bg-background max-lg:border-t lg:border-l">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
        <h2 className="font-display text-[17px] italic tabular-nums">Слайд {index + 1}</h2>
        <span className="eyebrow !text-[10px]">{definition.label}</span>
      </div>

      <div className="scroll-thin relative min-h-0 flex-1 overflow-y-auto">
        <Section title="Макет">
          <LayoutPicker value={slide.layout} onChange={(layout) => changeLayout(slide.id, layout)} />
        </Section>
        <Separator />

        <Section title="Содержание">
          {/* key — чтобы при переключении слайдов поля не сохраняли фокус и курсор предыдущего */}
          <motion.div
            key={slide.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: EASE_OUT_EXPO }}
            className="flex flex-col gap-4"
          >
            {fields.map((field) =>
              field.kind === 'list' ? (
                <ListFieldControl
                  key={field.key}
                  fieldKey={field.key}
                  label={field.label}
                  placeholder={field.placeholder}
                  addLabel={field.addLabel}
                  items={(values[field.key] as string[] | undefined) ?? []}
                  onChange={(items) => updateSlide(slide.id, { [field.key]: items } as Partial<Slide>)}
                  onFocusField={onFocusField}
                />
              ) : (
                <TextFieldControl
                  key={field.key}
                  fieldKey={field.key}
                  kind={field.kind}
                  label={field.label}
                  placeholder={field.placeholder}
                  optional={field.optional}
                  hint={field.hint}
                  maxLength={field.maxLength}
                  value={(values[field.key] as string | undefined) ?? ''}
                  onChange={(value) => updateSlide(slide.id, { [field.key]: value } as Partial<Slide>)}
                  onFocusField={onFocusField}
                />
              ),
            )}
          </motion.div>
        </Section>
        <Separator />

        <Section title="Заметки докладчика">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="field-notes" className="sr-only">
              Заметки докладчика
            </Label>
            <AutoTextarea
              id="field-notes"
              key={`notes-${slide.id}`}
              value={slide.notes ?? ''}
              maxLength={10_000}
              placeholder="Что сказать на этом слайде"
              onChange={(e) => updateSlide(slide.id, { notes: e.target.value })}
              className="min-h-[72px] text-[13px]"
              aria-describedby="field-notes-hint"
            />
            <p id="field-notes-hint" className="text-[11.5px] text-muted-foreground">
              Не видны на слайде. Попадают в заметки PPTX — их видно в режиме докладчика.
            </p>
          </div>
        </Section>
      </div>

      <div className="flex shrink-0 items-center gap-1 border-t border-border px-3 py-2.5">
        <Button variant="ghost" size="sm" onClick={() => duplicate(slide.id)}>
          <Copy />
          Дублировать
        </Button>
        {canSplitSlide(slide) && (
          <Button variant="ghost" size="sm" onClick={() => split(slide.id)}>
            <Scissors />
            Разделить
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto text-destructive hover:bg-destructive-soft hover:text-destructive"
          onClick={() => remove(slide.id)}
          disabled={total <= 1}
        >
          <Trash2 />
          Удалить
        </Button>
      </div>
    </aside>
  )
}
