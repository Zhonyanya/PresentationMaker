import type { LucideIcon } from 'lucide-react'
import type { Slide, SlideLayout, SlideOf } from '@/domain/presentation'
import type { PresentationTheme } from '@/theme/presentation-theme'
import type { SlideScene } from './scene'

/** Нейтральное содержимое слайда — используется при смене макета. */
export interface SlideContent {
  title: string
  subtitle?: string
  items: string[]
  columns?: {
    left: { title?: string; items: string[] }
    right: { title?: string; items: string[] }
  }
}

export interface RenderContext {
  theme: PresentationTheme
  /** Номер слайда, начиная с 1 */
  number: number
  total: number
  /** Порядковый номер раздела — для слайдов-разделителей */
  sectionNumber: number
}

type KeysOfType<S, T> = {
  [K in keyof S]-?: NonNullable<S[K]> extends T ? K : never
}[keyof S] &
  string

type EditableKeys<S> = Exclude<keyof S & string, 'id' | 'layout' | 'notes'>

export interface TextFieldDef<S> {
  kind: 'text' | 'textarea'
  key: Extract<KeysOfType<S, string>, EditableKeys<S>>
  label: string
  placeholder: string
  optional?: boolean
  maxLength: number
  hint?: string
}

export interface ListFieldDef<S> {
  kind: 'list'
  key: Extract<KeysOfType<S, string[]>, EditableKeys<S>>
  label: string
  placeholder: string
  addLabel: string
}

export type FieldDef<S> = TextFieldDef<S> | ListFieldDef<S>

/** Поля слайда без служебных — то, что создаёт `fromContent`. */
export type SlideFields<L extends SlideLayout> = Omit<SlideOf<L>, 'id' | 'notes' | 'layout'>

export interface LayoutDefinition<L extends SlideLayout = SlideLayout> {
  layout: L
  label: string
  description: string
  icon: LucideIcon
  /** Поля в правой панели редактора, в порядке отображения */
  fields: FieldDef<SlideOf<L>>[]
  fromContent(content: SlideContent): SlideFields<L>
  toContent(slide: SlideOf<L>): SlideContent
  buildScene(slide: SlideOf<L>, ctx: RenderContext): SlideScene
}

export type AnyLayoutDefinition = { [L in SlideLayout]: LayoutDefinition<L> }[SlideLayout]

export type { Slide }
