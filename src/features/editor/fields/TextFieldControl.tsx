import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { AutoTextarea } from './AutoTextarea'

interface TextFieldControlProps {
  fieldKey: string
  kind: 'text' | 'textarea'
  label: string
  placeholder: string
  optional?: boolean
  hint?: string
  maxLength: number
  value: string
  onChange: (value: string) => void
  onFocusField: (key: string | null) => void
}

export function TextFieldControl({ fieldKey, kind, label, placeholder, optional, hint, maxLength, value, onChange, onFocusField }: TextFieldControlProps) {
  const id = `field-${fieldKey}`
  const nearLimit = value.length > maxLength * 0.8
  const common = {
    id,
    value,
    placeholder,
    maxLength,
    'aria-describedby': hint ? `${id}-hint` : undefined,
    onFocus: () => onFocusField(fieldKey),
    onBlur: () => onFocusField(null),
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={id} className="text-[12.5px]">
          {label}
          {optional && <span className="font-normal text-muted-foreground">необязательно</span>}
        </Label>
        {nearLimit && (
          <span className={cn('text-[11px] tabular-nums text-muted-foreground', value.length >= maxLength && 'text-destructive')}>
            {value.length}/{maxLength}
          </span>
        )}
      </div>
      {kind === 'text' ? (
        <Input {...common} onChange={(e) => onChange(e.target.value)} className="h-9 text-[13.5px]" />
      ) : (
        <AutoTextarea {...common} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint && (
        <p id={`${id}-hint`} className="text-[11.5px] text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  )
}
