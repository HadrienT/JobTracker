import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Reason } from '@/mocks/contract'
import { Score } from '@/shared/ui/score'
import { TooltipProvider } from '@/shared/ui/tooltip'

const REASONS: Reason[] = [
  { code: 'title_match', delta: 25, evidence: 'Quantitative Developer' },
  { code: 'senior_only', delta: -30, evidence: '8+ years required' },
]

describe('Score', () => {
  it('shows the tabular score', () => {
    render(<Score score={87} tier="strong" reasons={[]} />)
    expect(screen.getByText('87')).toHaveClass('font-tabular')
  })

  it('reveals its Reasons on hover', async () => {
    const user = userEvent.setup()
    render(
      <TooltipProvider delayDuration={0}>
        <Score score={58} tier="possible" reasons={REASONS} />
      </TooltipProvider>,
    )
    await user.hover(screen.getByText('58'))
    expect(await screen.findByText('title_match')).toBeInTheDocument()
    expect(screen.getByText('senior_only')).toBeInTheDocument()
  })
})
