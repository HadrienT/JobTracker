import { useSyncExternalStore } from 'react'

/** Below Tailwind's `md` breakpoint: a phone, held upright. Keep in step with the `md:` classes. */
const MOBILE_QUERY = '(max-width: 767px)'

function mediaQueryList(query: string): MediaQueryList | null {
  // jsdom has no matchMedia: tests render the desktop layout unless they stub it.
  return typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = mediaQueryList(query)
      list?.addEventListener('change', onChange)
      return () => {
        list?.removeEventListener('change', onChange)
      }
    },
    () => mediaQueryList(query)?.matches ?? false,
    () => false,
  )
}

/**
 * For what CSS alone can't switch: the virtualizer's row height, a panel that becomes a drawer.
 * Everything else uses `md:` classes.
 */
export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_QUERY)
}
