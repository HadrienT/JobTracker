import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Age } from '@/shared/ui/age'

const NOW = new Date('2026-09-17T09:00:00Z')

describe('Age', () => {
  it('renders days as `Nd`', () => {
    render(<Age postedAt={null} firstSeenAt="2026-09-14T09:00:00Z" staleAfterDays={30} now={NOW} />)
    expect(screen.getByText('3d')).toBeInTheDocument()
  })

  it('renders full weeks as `Nw` past 14 days', () => {
    render(<Age postedAt={null} firstSeenAt="2026-09-03T09:00:00Z" staleAfterDays={30} now={NOW} />)
    expect(screen.getByText('2w')).toBeInTheDocument()
  })

  it('carries a warning style once past half of staleAfterDays', () => {
    render(<Age postedAt={null} firstSeenAt="2026-08-15T09:00:00Z" staleAfterDays={30} now={NOW} />)
    expect(screen.getByText('4w')).toHaveClass('text-warning')
  })

  it('stays neutral before the staleness threshold', () => {
    render(<Age postedAt={null} firstSeenAt="2026-09-14T09:00:00Z" staleAfterDays={30} now={NOW} />)
    expect(screen.getByText('3d')).not.toHaveClass('text-warning')
  })

  it('prefers postedAt over firstSeenAt when it predates it', () => {
    render(
      <Age postedAt="2026-09-10T09:00:00Z" firstSeenAt="2026-09-14T09:00:00Z" staleAfterDays={30} now={NOW} />,
    )
    expect(screen.getByText('7d')).toBeInTheDocument()
  })

  it('ignores a postedAt that postdates firstSeenAt (a source backdating trick)', () => {
    render(
      <Age postedAt="2026-09-16T09:00:00Z" firstSeenAt="2026-09-14T09:00:00Z" staleAfterDays={30} now={NOW} />,
    )
    expect(screen.getByText('3d')).toBeInTheDocument()
  })
})
