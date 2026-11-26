import { useEffect, useRef, useState } from 'react'
import { FileUp, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { type Brandbook } from '@/domain/brandbook'
import { BRANDBOOK_ACCEPT, readBrandbook } from '@/lib/brandbook-import'
import { FileImportError } from '@/lib/file-import'

interface Props {
  value?: Brandbook
  onChange: (value?: Brandbook) => void
  loading: boolean
  onLoading: (loading: boolean) => void
}

export function BrandbookField({ value, onChange, loading, onLoading }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const version = useRef(0)
  const [error, setError] = useState('')
  useEffect(() => () => { version.current++ }, [])

  const load = async (file: File) => {
    const current = ++version.current
    onLoading(true)
    setError('')
    try {
      const brandbook = await readBrandbook(file)
      if (current === version.current) onChange(brandbook)
    } catch (cause) {
      if (current === version.current) setError(cause instanceof FileImportError ? cause.message : 'Не удалось загрузить брендбук.')
    } finally {
      if (current === version.current) onLoading(false)
    }
  }

  return (
    <fieldset className="flex min-w-0 flex-col gap-2">
      <legend className="eyebrow mb-2">Брендбук — необязательно</legend>
      <div className="flex flex-wrap items-center gap-2">
        <input ref={input} type="file" accept={BRANDBOOK_ACCEPT} className="hidden" onChange={(event) => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (file) void load(file)
        }} />
        <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => input.current?.click()}>
          {loading ? <Loader2 className="animate-spin" /> : <FileUp />}
          {loading ? 'Читаем брендбук…' : value ? 'Заменить брендбук' : 'Добавить брендбук'}
        </Button>
        {value && <>
          <span className="min-w-0 max-w-full break-words text-sm">{value.name}</span>
          <Button type="button" variant="ghost" size="sm" aria-label="Убрать брендбук" disabled={loading} onClick={() => { onChange(); setError('') }}><X /></Button>
        </>}
      </div>
      <p className="text-xs text-muted-foreground">Из PPTX и POTX загрузим два цвета темы и шрифты заголовков и текста. Из PDF — только цвета. До 10 МБ.</p>
      {value && <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
        {(['primary', 'accent'] as const).map((key) => (
          <label key={key} className="flex items-center gap-2">
            <input type="color" className="size-6 cursor-pointer border-0 bg-transparent p-0" value={value[key]}
              onChange={(event) => onChange({ ...value, [key]: event.target.value.toUpperCase() })} />
            {key === 'primary' ? 'Основной' : 'Акцентный'} · {value[key]}
          </label>
        ))}
        {value.headingFont && <span>Заголовки · {value.headingFont}</span>}
        {value.bodyFont && <span>Текст · {value.bodyFont}</span>}
      </div>}
      {error && <p role="alert" className="text-xs font-medium text-destructive">{error}</p>}
    </fieldset>
  )
}
