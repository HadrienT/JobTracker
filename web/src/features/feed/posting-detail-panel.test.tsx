import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { PostingDetailPanel } from '@/features/feed/posting-detail-panel'
import { useEscapeKey } from '@/features/feed/use-keyboard-shortcuts'
import { POSTINGS } from '@/mocks/data'
import { TooltipProvider } from '@/shared/ui/tooltip'

/** Mirrors real usage: the panel opens from a trigger (a row), and Escape closes it. */
function Harness({ postingId }: { postingId: string }) {
  const [open, setOpen] = useState(false)
  useEscapeKey(() => {
    setOpen(false)
  })
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          setOpen(true)
        }}
      >
        Row trigger
      </button>
      {open && (
        <PostingDetailPanel
          postingId={postingId}
          onClose={() => {
            setOpen(false)
          }}
        />
      )}
    </div>
  )
}

async function renderOpenPanel(postingId: string) {
  const user = userEvent.setup()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Harness postingId={postingId} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  const trigger = screen.getByRole('button', { name: 'Row trigger' })
  trigger.focus()
  await user.click(trigger)
  return { ...utils, user, trigger }
}

describe('PostingDetailPanel', () => {
  it('renders as an accessible modal with no serious axe violations', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const { container } = await renderOpenPanel(target.posting_id)
    await screen.findByText(target.title)
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('shows the score reasons with their evidence', async () => {
    const target = POSTINGS.find((p) => p.reasons.length > 0)
    if (!target) throw new Error('no fixture posting has reasons')
    await renderOpenPanel(target.posting_id)
    await screen.findByText(target.title)
    const firstReason = target.reasons[0]
    if (!firstReason) throw new Error('unreachable')
    expect(screen.getByText(firstReason.code)).toBeInTheDocument()
  })

  it('traps Tab focus inside the panel', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const { user } = await renderOpenPanel(target.posting_id)
    await screen.findByText(target.title)

    const closeButton = screen.getByRole('button', { name: 'Close' })
    const applyLink = await screen.findByRole('link', { name: /Open original posting/ })

    applyLink.focus()
    expect(document.activeElement).toBe(applyLink)
    await user.tab()
    expect(document.activeElement).toBe(closeButton)
  })

  it('restores focus to the triggering element when closed with Escape', async () => {
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const { user, trigger } = await renderOpenPanel(target.posting_id)
    await screen.findByText(target.title)
    expect(document.activeElement).not.toBe(trigger)

    await user.keyboard('{Escape}')

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(document.activeElement).toBe(trigger)
  })

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn()
    const target = POSTINGS[0]
    if (!target) throw new Error('fixture is empty')
    const user = userEvent.setup()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <PostingDetailPanel postingId={target.posting_id} onClose={onClose} />
        </TooltipProvider>
      </QueryClientProvider>,
    )
    await screen.findByText(target.title)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
