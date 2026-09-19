import { useEffect, useRef, useState } from 'react'
import { type ApplicationStatus, useSetApplicationStatus, useSetNote } from '@/api/queries'
import { STATUS_OPTIONS } from '@/features/filters/defaults'
import type { PostingDetailOut } from '@/mocks/contract'

const NOTE_MAX_LENGTH = 4000

interface TrackingSectionProps {
  posting: PostingDetailOut
}

/**
 * Your side of the posting: where the application stands, and a note. The status saves the
 * moment it changes; the note saves when you leave the field — and when the panel closes with
 * the field still focused, because Escape unmounts without a blur and a note lost that way
 * would be the worst kind of bug in a tool meant to hold your reminders.
 */
export function TrackingSection({ posting }: TrackingSectionProps) {
  const setStatus = useSetApplicationStatus()
  const setNote = useSetNote()
  const [draft, setDraft] = useState(posting.note)
  const saved = useRef(posting.note)
  const latest = useRef({ draft, postingId: posting.posting_id })
  useEffect(() => {
    latest.current = { draft, postingId: posting.posting_id }
  })

  function saveNote() {
    if (latest.current.draft === saved.current) return
    saved.current = latest.current.draft
    setNote.mutate({ postingId: latest.current.postingId, note: latest.current.draft })
  }

  useEffect(
    () => () => {
      if (latest.current.draft !== saved.current) {
        setNote.mutate({ postingId: latest.current.postingId, note: latest.current.draft })
      }
    },
    // The cleanup must see the *latest* draft through the ref, and run once, on unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  return (
    <section aria-label="Tracking" className="flex flex-col gap-3 rounded-md border border-border p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Your application</h3>

      <label className="flex items-center justify-between gap-3 text-sm text-text-secondary">
        Status
        <select
          aria-label="Application status"
          value={posting.application_status ?? ''}
          onChange={(event) => {
            const value = event.target.value
            setStatus.mutate({
              postingId: posting.posting_id,
              value: value === '' ? null : (value as ApplicationStatus),
            })
          }}
          className="rounded-md border border-border bg-surface px-2 py-1 text-text-primary"
        >
          <option value="">Not tracking</option>
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {setStatus.isError && <p className="text-xs text-danger">Couldn&apos;t save the status.</p>}

      <label className="flex flex-col gap-1 text-sm text-text-secondary">
        Notes
        <textarea
          aria-label="Notes"
          value={draft}
          maxLength={NOTE_MAX_LENGTH}
          rows={3}
          placeholder="Who you spoke to, what was said, what to do next…"
          onChange={(event) => {
            setDraft(event.target.value)
          }}
          onBlur={saveNote}
          className="resize-y rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary"
        />
      </label>
      {setNote.isError && <p className="text-xs text-danger">Couldn&apos;t save the note.</p>}
    </section>
  )
}
