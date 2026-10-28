import type { StateStorage } from 'zustand/middleware'

/**
 * localStorage, который не роняет приложение: в приватном режиме,
 * при запрете cookies или переполнении хранилища просто ничего не сохраняет.
 */
export const safeStorage: StateStorage = {
  getItem: (name) => {
    try {
      return globalThis.localStorage?.getItem(name) ?? null
    } catch {
      return null
    }
  },
  setItem: (name, value) => {
    try {
      globalThis.localStorage?.setItem(name, value)
    } catch {
      /* хранилище недоступно — работаем без сохранения */
    }
  },
  removeItem: (name) => {
    try {
      globalThis.localStorage?.removeItem(name)
    } catch {
      /* noop */
    }
  },
}
