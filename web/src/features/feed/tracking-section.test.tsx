import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { PostingDetailPanel } from '@/features/feed/posting-detail-panel'
import { POSTINGS } from '@/mocks/data'
import { server } from '@/mocks/server'
import { TooltipProvider } from '@/shared/ui/tooltip'

function renderPanel(postingId: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <PostingDetailPanel postingId={postingId} onClose={() => undefined} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...utils, queryClient, user: userEvent.setup() }
}

function target() {
  const posting = POSTINGS[0]
  if (!posting) throw new Error('fixture is empty')
  return posting
}

/** Records every body POSTed to `/postings/:id/<route>`. */
function record(route: 'status' | 'note') {
  const bodies: unknown[] = []
  server.use(
    http.post(`*/postings/:id/${route}`, async ({ request }) => {
      bodies.push(await request.json())
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return bodies
}

describe('TrackingSection', () => {
  it('starts as "Not tracking" with an empty note', async () => {
    renderPanel(target().posting_id)
    expect(await screen.findByRole('combobox', { name: 'Application status' })).toHaveValue('')
    expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveValue('')
  })

  it('saves a status the moment it changes, and shows it', async () => {
    const bodies = record('status')
    const { user } = renderPanel(target().posting_id)
    const select = await screen.findByRole('combobox', { name: 'Application status' })

    await user.selectOptions(select, 'interview')

    await waitFor(() => {
      expect(bodies).toEqual([{ status: 'interview' }])
    })
    expect(select).toHaveValue('interview')
  })

  it('stops tracking when "Not tracking" is picked', async () => {
    const bodies = record('status')
    const { user } = renderPanel(target().posting_id)
    const select = await screen.findByRole('combobox', { name: 'Application status' })
    await user.selectOptions(select, 'applied')
    await user.selectOptions(select, '')

    await waitFor(() => {
      expect(bodies).toEqual([{ status: 'applied' }, { status: null }])
    })
  })

  it('saves the note when the field is left', async () => {
    const bodies = record('note')
    const { user } = renderPanel(target().posting_id)
    const notes = await screen.findByRole('textbox', { name: 'Notes' })

    await user.type(notes, 'call Anna on Monday')
    expect(bodies).toEqual([]) // typing alone does not save
    await user.tab()

    await waitFor(() => {
      expect(bodies).toEqual([{ note: 'call Anna on Monday' }])
    })
  })

  it('does not save an untouched note', async () => {
    const bodies = record('note')
    const { user } = renderPanel(target().posting_id)
    const notes = await screen.findByRole('textbox', { name: 'Notes' })

    await user.click(notes)
    await user.tab()

    expect(bodies).toEqual([])
  })

  it('saves a half-typed note when the panel closes without a blur', async () => {
    const bodies = record('note')
    const { user, unmount } = renderPanel(target().posting_id)
    await user.type(await screen.findByRole('textbox', { name: 'Notes' }), 'do not lose me')

    unmount() // what Escape does: the field never gets to blur

    await waitFor(() => {
      expect(bodies).toEqual([{ note: 'do not lose me' }])
    })
  })

  it('brings back a saved note and status the next time the posting is opened', async () => {
    const { user, unmount } = renderPanel(target().posting_id)
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Application status' }), 'offer')
    await user.type(screen.getByRole('textbox', { name: 'Notes' }), 'verbal offer')
    await user.tab()
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveValue('verbal offer')
    })
    unmount()

    renderPanel(target().posting_id)
    expect(await screen.findByRole('combobox', { name: 'Application status' })).toHaveValue('offer')
    await waitFor(() => {
      expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveValue('verbal offer')
    })
  })

  it('says so when the note cannot be saved', async () => {
    server.use(http.post('*/postings/:id/note', () => new HttpResponse(null, { status: 500 })))
    const { user } = renderPanel(target().posting_id)
    await user.type(await screen.findByRole('textbox', { name: 'Notes' }), 'x')
    await user.tab()

    expect(await screen.findByText(/Couldn.t save the note/)).toBeInTheDocument()
  })
})
