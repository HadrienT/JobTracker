import { useCallback, useRef, useState, type ReactNode } from 'react'
import { ToastContext, type ToastAction } from '@/features/favorites/toast-context'

interface ToastItem {
  id: number
  message: string
  action?: ToastAction
}

const TOAST_DURATION_MS = 5000

/**
 * A rollback needs to be *seen*, not just silently undone in the cache
 * (blueprint/wp/WP11-web-filters.md §4: "rollback + toast"). Hiding also gets
 * an "Undo" action here rather than a CSS remove-animation with its own undo
 * affordance — same outcome, far less to get wrong.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(0)

  const show = useCallback((message: string, action?: ToastAction) => {
    const id = nextId.current
    nextId.current += 1
    setToasts((current) => [...current, { id, message, action }])
    setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, TOAST_DURATION_MS)
  }, [])

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="pointer-events-auto flex items-center gap-3 rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-text-primary shadow-lg"
          >
            <span>{toast.message}</span>
            {toast.action && (
              <button type="button" className="font-medium text-tier-possible hover:underline" onClick={toast.action.onClick}>
                {toast.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
