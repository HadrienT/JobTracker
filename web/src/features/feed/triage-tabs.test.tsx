import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PostingsFilter } from '@/api/queries'
import { TriageTabs } from '@/features/feed/triage-tabs'
import { DEFAULT_FILTER, DEFAULT_TIERS, feedViewOf, isDefaultFilter } from '@/features/filters/defaults'
import { decodeFeedState, encodeFeedState } from '@/features/filters/url-codec'

/** Clicks a tab and returns the filter the feed would then be reading. */
async function pick(tab: string, from: PostingsFilter = DEFAULT_FILTER): Promise<PostingsFilter> {
  const onChange = vi.fn<(patch: Partial<PostingsFilter>) => void>()
  const { unmount } = render(<TriageTabs filter={from} onChange={onChange} />)
  await userEvent.click(screen.getByRole('tab', { name: tab }))
  unmount()
  return { ...from, ...onChange.mock.calls[0]?.[0] }
}

describe('TriageTabs — Filtered out', () => {
  it('reads back exactly what the pipeline rejected, and nothing else', async () => {
    const filter = await pick('Filtered out')
    expect(filter.tiers).toEqual(['rejected'])
    expect(filter.triage).toBeNull()
    expect(feedViewOf(filter)).toBe('rejected')
    expect(isDefaultFilter(filter)).toBe(true)
  })

  it('survives the URL: the tab is still selected after a reload', async () => {
    const filter = await pick('Filtered out')
    const reloaded = decodeFeedState(encodeFeedState({ filter: { ...filter, rejection_reasons: ['senior_only'] }, sort: 'score' }))
    expect(feedViewOf(reloaded.filter)).toBe('rejected')
    expect(reloaded.filter.rejection_reasons).toEqual(['senior_only'])

    render(<TriageTabs filter={reloaded.filter} onChange={vi.fn()} />)
    expect(screen.getByRole('tab', { name: 'Filtered out' })).toHaveAttribute('aria-selected', 'true')
  })

  it('goes back to the inbox with the default tiers and no leftover reason', async () => {
    const rejected = { ...(await pick('Filtered out')), rejection_reasons: ['not_quant'] }
    const inbox = await pick('Inbox', rejected)
    expect(inbox.tiers).toEqual(DEFAULT_TIERS)
    expect(inbox.rejection_reasons).toEqual([])
    expect(feedViewOf(inbox)).toBe('inbox')
  })

  it('shows a rescued posting in Maybe: that list is not narrowed to the tiers the pipeline kept', async () => {
    const maybe = await pick('Maybe', await pick('Filtered out'))
    expect(maybe.triage).toBe('maybe')
    expect(maybe.tiers).toContain('rejected')
    expect(isDefaultFilter(maybe)).toBe(true)
  })
})
