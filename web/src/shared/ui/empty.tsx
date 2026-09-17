/**
 * The single rendering of "not stated" in the whole front — an absent salary, an
 * unresolved location or an unknown closing date all look like this, and never
 * like a zero. See blueprint/wp/WP09-web-foundations.md §4.
 */
export function Empty() {
  return (
    <span className="font-tabular text-text-tertiary" aria-label="not specified">
      —
    </span>
  )
}
