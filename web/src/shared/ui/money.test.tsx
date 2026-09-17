import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Money } from '@/shared/ui/money'

describe('Money', () => {
  it('renders Empty, never 0, when the amount is absent', () => {
    render(<Money amountMin={null} amountMax={null} currency={null} period={null} />)
    const empty = screen.getByLabelText('not specified')
    expect(empty).toHaveTextContent('—')
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('renders a range in the origin currency, unconverted', () => {
    render(<Money amountMin="60000" amountMax="90000" currency="EUR" period="year" />)
    expect(screen.getByText(/€60k.*90k/)).toBeInTheDocument()
  })
})
