const LAST_VISIT_KEY = 'jobtracker.lastVisit'
const SESSION_KEY = 'jobtracker.previousVisit'

let cached: string | null | undefined

function read(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null // storage can be blocked (private window, site data off): "new" simply never shows
  }
}

function write(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // same: a missing marker is a missing badge, never an error
  }
}

/**
 * When you last opened the app *before* this visit — what "new" is measured against.
 *
 * The stored time moves forward once per tab session, not once per page load: reloading (or
 * flipping between tabs of the app) must not make the postings you have not looked at yet look
 * old. The previous visit is therefore parked in `sessionStorage` on the first load of a tab
 * and reused by every later load in it. `null` on a first-ever visit: everything would be
 * "new", which tells you nothing.
 */
export function previousVisit(): string | null {
  if (cached !== undefined) return cached
  const inSession = read(sessionStorage, SESSION_KEY)
  if (inSession !== null) {
    cached = inSession === '' ? null : inSession
    return cached
  }
  const stored = read(localStorage, LAST_VISIT_KEY)
  write(sessionStorage, SESSION_KEY, stored ?? '')
  write(localStorage, LAST_VISIT_KEY, new Date().toISOString())
  cached = stored
  return cached
}

/** A posting is new when the collector first saw it after your previous visit. */
export function isNewSinceLastVisit(firstSeenAt: string): boolean {
  const since = previousVisit()
  return since !== null && firstSeenAt > since
}

/** Tests only: forget what was computed for this page load. */
export function resetPreviousVisitForTests(): void {
  cached = undefined
}
