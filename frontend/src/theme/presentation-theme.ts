/**
 * КОРПОРАТИВНАЯ ТЕМА ПРЕЗЕНТАЦИЙ
 * ==============================
 *
 * ⚠️ Это ВРЕМЕННАЯ нейтральная тема. Цвета, шрифты и макеты подобраны для
 * прототипа и НЕ являются официальным оформлением министерства.
 * Логотип не задан намеренно.
 *
 * Как заменить на брендбук — см. README.md, раздел «Корпоративная тема».
 * Коротко: поменяйте значения ниже. И превью в редакторе, и экспорт в PPTX
 * берут оформление только отсюда.
 *
 * Все размеры — в дюймах (так работает PowerPoint и PptxGenJS),
 * размеры шрифтов — в пунктах (pt).
 */

export interface FontSizeRange {
  /** Размер по умолчанию */
  max: number
  /** Минимальный размер, до которого шрифт уменьшается, если текст не помещается */
  min: number
}

export interface ThemeLogo {
  /**
   * URL изображения (PNG/JPG/SVG). Удобнее всего положить файл в /public
   * и указать '/logo.png', либо импортировать: `import logo from './logo.png'`.
   */
  src: string
  /** Ширина и высота области логотипа в дюймах; изображение вписывается с сохранением пропорций */
  width: number
  height: number
  /** Показывать на титульном и заключительном слайдах (на тёмном фоне) */
  onDarkSlides: boolean
  /** Отдельная версия логотипа для тёмного фона, если нужна */
  srcOnDark?: string
}

export interface PresentationTheme {
  id: string
  name: string
  /** false — тема временная. Интерфейс покажет предупреждение. */
  isOfficial: boolean
  slide: { width: number; height: number }
  colors: {
    primary: string
    accent: string
    accentOnPrimary: string
    background: string
    surface: string
    text: string
    textMuted: string
    textOnPrimary: string
    textOnPrimaryMuted: string
    divider: string
  }
  fonts: {
    /** Имя шрифта в PPTX. Шрифт должен быть установлен у пользователя, иначе PowerPoint подставит замену. */
    heading: string
    body: string
    /** CSS-запасные шрифты для превью в браузере */
    cssFallback: string
  }
  typography: {
    coverTitle: FontSizeRange
    coverSubtitle: FontSizeRange
    caption: number
    sectionNumber: number
    sectionTitle: FontSizeRange
    heading: FontSizeRange
    columnHeading: number
    body: FontSizeRange
    bullets: FontSizeRange
    footer: number
    /**
     * Аварийный минимум, pt. Если текст не помещается даже при минимальном размере
     * поля, шрифт уменьшается до этого значения, чтобы текст не вышел за рамку.
     * Редактор при этом предупреждает пользователя.
     */
    absoluteMinFontSize: number
    /** Межстрочный интервал (множитель) */
    lineSpacing: number
    /** Отступ после абзаца, pt */
    paragraphSpacing: number
    /** Отступ текста от маркера списка, pt */
    bulletIndent: number
  }
  spacing: {
    /** Поля слева и справа */
    marginX: number
    /** Верх заголовка на контентных слайдах */
    headingTop: number
    headingHeight: number
    /** Начало области контента */
    contentTop: number
    /** Нижняя граница области контента */
    contentBottom: number
    columnGap: number
  }
  logo: ThemeLogo | null
  footer: {
    /** Текст в нижнем колонтитуле контентных слайдов. Пустая строка — без текста. */
    text: string
    showSlideNumber: boolean
  }
}

export const presentationTheme: PresentationTheme = {
  id: 'neutral-temporary',
  name: 'Временная нейтральная тема',
  isOfficial: false,

  // 16:9, как «Широкоэкранный» формат PowerPoint
  slide: { width: 13.333, height: 7.5 },

  colors: {
    primary: '#1F3A5F',
    accent: '#2F6DB5',
    accentOnPrimary: '#8EB2E0',
    background: '#FFFFFF',
    surface: '#F2F4F7',
    text: '#1B2430',
    textMuted: '#5A6575',
    textOnPrimary: '#FFFFFF',
    textOnPrimaryMuted: '#C5D1E1',
    divider: '#D7DCE3',
  },

  // Arial есть на любом компьютере с PowerPoint — файл откроется без подмены шрифтов
  fonts: {
    heading: 'Arial',
    body: 'Arial',
    cssFallback: "'Helvetica Neue', Helvetica, 'Liberation Sans', sans-serif",
  },

  typography: {
    coverTitle: { max: 40, min: 26 },
    coverSubtitle: { max: 20, min: 14 },
    caption: 14,
    sectionNumber: 54,
    sectionTitle: { max: 40, min: 26 },
    heading: { max: 30, min: 20 },
    columnHeading: 18,
    body: { max: 20, min: 12 },
    bullets: { max: 22, min: 12 },
    footer: 10,
    absoluteMinFontSize: 9,
    lineSpacing: 1.1,
    paragraphSpacing: 10,
    bulletIndent: 20,
  },

  spacing: {
    marginX: 0.8,
    headingTop: 0.75,
    headingHeight: 1.05,
    contentTop: 2.0,
    contentBottom: 6.65,
    columnGap: 0.6,
  },

  logo: null,

  footer: {
    text: '',
    showSlideNumber: true,
  },
}
