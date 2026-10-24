/**
 * Бегущая строка с тезисами о продукте — как рубрикатор на обложке журнала.
 * Движется непрерывно; при «Уменьшить движение» стоит на месте.
 */
const THESES = [
  'Из доклада — в презентацию',
  'Корпоративный стиль на каждом слайде',
  'Редактируемый файл PowerPoint',
  'Без ручной вёрстки',
  'Ваш текст — ваши формулировки',
]

export function ValueTicker() {
  const row = (hidden: boolean) => (
    <ul className="flex shrink-0 items-center" aria-hidden={hidden || undefined}>
      {THESES.map((text) => (
        <li key={text} className="flex items-center">
          <span className="px-8 font-display text-[clamp(1.6rem,3vw,2.6rem)] leading-none font-[360] tracking-[-0.02em] whitespace-nowrap italic">
            {text}
          </span>
          <span className="size-1.5 rotate-45 bg-brand" aria-hidden />
        </li>
      ))}
    </ul>
  )

  return (
    <div className="relative overflow-hidden border-t border-border py-7">
      <p className="sr-only">{THESES.join('. ')}</p>
      {/* Края растворяются в бумаге */}
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-24 bg-gradient-to-r from-background to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-24 bg-gradient-to-l from-background to-transparent" />
      <div className="flex w-max animate-[ticker_48s_linear_infinite] will-change-transform motion-reduce:animate-none" aria-hidden>
        {row(false)}
        {row(true)}
      </div>
    </div>
  )
}
