import { useEffect } from 'react'

/**
 * blueprint/wp/WP10-web-feed.md §4 — every shortcut here is a no-op while focus
 * sits in a text field, so typing "job" into search doesn't hide three postings.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
}

export interface FeedShortcutHandlers {
  onNext: () => void
  onPrev: () => void
  onOpen: () => void
  onOpenSource: () => void
  onToggleFavorite: () => void
  onHide: () => void
  onFocusSearch: () => void
  onEscape: () => void
}

/** `j`/`k`/`Enter`/`o`/`f`/`h`/`/` — gated by `enabled` (e.g. off while the detail modal is open). */
export function useFeedKeyboardShortcuts(handlers: FeedShortcutHandlers, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return undefined

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === '/') {
        if (isTypingTarget(event.target)) return
        event.preventDefault()
        handlers.onFocusSearch()
        return
      }
      if (isTypingTarget(event.target)) return
      switch (event.key) {
        case 'j':
          event.preventDefault()
          handlers.onNext()
          break
        case 'k':
          event.preventDefault()
          handlers.onPrev()
          break
        case 'Enter':
          handlers.onOpen()
          break
        case 'o':
          handlers.onOpenSource()
          break
        case 'f':
          handlers.onToggleFavorite()
          break
        case 'h':
          handlers.onHide()
          break
        case 'Escape':
          handlers.onEscape()
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [handlers, enabled])
}

/**
 * A second, always-on `Échap` listener for the detail panel itself: the panel is
 * mounted while `FeedList`'s shortcuts are disabled, so closing it needs its own
 * unconditional binding. Once it closes, `FeedList`'s own `onEscape` (in the
 * handlers above) takes over and clears the row selection on the next press.
 */
export function useEscapeKey(onEscape: () => void): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onEscape()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onEscape])
}
