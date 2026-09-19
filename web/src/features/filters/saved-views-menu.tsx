import { useState } from 'react'
import { deleteView, loadViews, saveView, type SavedView } from '@/features/filters/saved-views'

/**
 * Named searches, kept in this browser. A view is just a query string — the same one the
 * address bar already holds — so applying one is a navigation, and nothing here can drift from
 * what the filters mean.
 */
export function SavedViews() {
  const [views, setViews] = useState<SavedView[]>(() => loadViews())
  const [name, setName] = useState('')

  function apply(view: SavedView) {
    const path = window.location.pathname.startsWith('/p/') ? '/' : window.location.pathname
    window.history.pushState(null, '', `${path}${view.search}`)
    // The URL is the state (ADR-008); this is how the screens are told it moved.
    window.dispatchEvent(new PopStateEvent('popstate'))
  }

  return (
    <details className="relative">
      <summary className="cursor-pointer select-none rounded-md border border-border px-2 py-1 text-sm text-text-secondary hover:text-text-primary">
        Views
      </summary>
      <div className="absolute left-0 top-full z-30 mt-1 flex w-72 flex-col gap-2 rounded-md border border-border bg-surface p-3 shadow-lg">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            setViews(saveView(name, window.location.search))
            setName('')
          }}
        >
          <input
            aria-label="Name for this view"
            value={name}
            onChange={(event) => {
              setName(event.target.value)
            }}
            placeholder="Name the current search…"
            maxLength={60}
            className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary placeholder:text-text-tertiary"
          />
          <button
            type="submit"
            disabled={name.trim() === ''}
            className="rounded-md border border-border px-2 py-1 text-sm text-text-primary hover:bg-surface-elevated disabled:opacity-40"
          >
            Save
          </button>
        </form>

        {views.length === 0 ? (
          <p className="text-xs text-text-tertiary">No saved views yet.</p>
        ) : (
          <ul aria-label="Saved views" className="flex max-h-64 flex-col overflow-y-auto">
            {views.map((view) => (
              <li key={view.name} className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate rounded-md px-2 py-1 text-left text-sm text-text-primary hover:bg-surface-elevated"
                  onClick={() => {
                    apply(view)
                  }}
                >
                  {view.name}
                </button>
                <button
                  type="button"
                  aria-label={`Delete view ${view.name}`}
                  className="rounded-md px-2 py-1 text-text-tertiary hover:bg-surface-elevated hover:text-text-primary"
                  onClick={() => {
                    setViews(deleteView(view.name))
                  }}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  )
}
