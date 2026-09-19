const KEY = 'jobtracker.savedViews'
const MAX_VIEWS = 30

export interface SavedView {
  name: string
  /** The query string as it was in the address bar: filters and sort, nothing else. */
  search: string
}

function isSavedView(value: unknown): value is SavedView {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as SavedView).name === 'string' &&
    typeof (value as SavedView).search === 'string'
  )
}

export function loadViews(): SavedView[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed: unknown = raw === null ? [] : JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(isSavedView) : []
  } catch {
    return [] // blocked storage or a corrupted value: no saved views, never a crash
  }
}

function store(views: SavedView[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(views))
    return true
  } catch {
    return false
  }
}

/** Saving under an existing name replaces that view: the name is what you remember it by. */
export function saveView(name: string, search: string): SavedView[] {
  const trimmed = name.trim()
  if (trimmed === '') return loadViews()
  const others = loadViews().filter((view) => view.name !== trimmed)
  const views = [{ name: trimmed, search }, ...others].slice(0, MAX_VIEWS)
  return store(views) ? views : loadViews()
}

export function deleteView(name: string): SavedView[] {
  const views = loadViews().filter((view) => view.name !== name)
  return store(views) ? views : loadViews()
}
