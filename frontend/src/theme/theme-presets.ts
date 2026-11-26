import urfuCover from './assets/urfu-cover.png?url'
import urfuContent from './assets/urfu-content.png?url'
import type { Brandbook } from '@/domain/brandbook'
import { presentationTheme, themeFor, type PresentationTheme, type ThemeId } from './presentation-theme'

const urfuTheme: PresentationTheme = {
  ...presentationTheme,
  id: 'urfu',
  name: 'УрФУ',
  isOfficial: true,
  artwork: { cover: urfuCover, content: urfuContent, coverTextWidth: 8.05 },
  colors: {
    ...presentationTheme.colors,
    primary: '#1E4391',
    accent: '#1E4391',
    accentOnPrimary: '#FCEC4F',
    surface: '#EDF3FA',
    text: '#292929',
    textMuted: '#4B647D',
    textOnPrimaryMuted: '#FFFFFF',
    divider: '#D6DFEA',
  },
  fonts: { heading: 'Montserrat', body: 'Montserrat', cssFallback: 'Arial, sans-serif' },
  typography: {
    ...presentationTheme.typography,
    coverTitle: { max: 35, min: 26 },
    coverSubtitle: { max: 18, min: 14 },
    heading: { max: 27, min: 19 },
    body: { max: 19, min: 14 },
  },
  spacing: { ...presentationTheme.spacing, marginX: 1.03, headingTop: 1.15,
    headingHeight: 0.90, contentTop: 2.17, contentBottom: 6.53 },
}

export function resolvePresentationTheme(id?: ThemeId, brandbook?: Brandbook): PresentationTheme {
  return id === 'urfu' ? urfuTheme : themeFor(brandbook)
}


// The Node exporter has no web server to resolve the Vite asset URLs.
export async function prepareThemeForExport(theme: PresentationTheme): Promise<PresentationTheme> {
  if (typeof window !== 'undefined' || !theme.artwork || theme.artwork !== urfuTheme.artwork) return theme
  const [{ default: cover }, { default: content }] = await Promise.all([
    import('./assets/urfu-cover.png?inline'),
    import('./assets/urfu-content.png?inline'),
  ])
  return { ...theme, artwork: { ...theme.artwork, cover, content } }
}
