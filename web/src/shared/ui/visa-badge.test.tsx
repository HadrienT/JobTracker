import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { VisaStatus } from '@/mocks/contract'
import { VisaBadge } from '@/shared/ui/visa-badge'

const CASES: { status: VisaStatus; glyph: string; label: string }[] = [
  { status: 'sponsors', glyph: '✓', label: 'sponsors' },
  { status: 'no', glyph: '✗', label: 'no visa' },
  { status: 'unknown', glyph: '?', label: 'visa' },
]

describe('VisaBadge', () => {
  it.each(CASES)('renders a glyph and a label for "$status"', ({ status, glyph, label }) => {
    render(<VisaBadge status={status} />)
    expect(screen.getByText(glyph)).toBeInTheDocument()
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('gives each of the three states a visually distinct tone', () => {
    const rendered = CASES.map(({ status }) => {
      const { container } = render(<VisaBadge status={status} />)
      return container.querySelector('[data-testid="visa-badge"]')?.className
    })
    expect(new Set(rendered).size).toBe(3)
  })
})
