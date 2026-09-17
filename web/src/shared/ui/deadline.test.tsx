import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Deadline } from '@/shared/ui/deadline'

const NOW = new Date('2026-09-17T09:00:00Z')

describe('Deadline', () => {
  it('renders "closes in Nd" in red when a closing date exists', () => {
    render(<Deadline closesAt="2026-09-23T09:00:00Z" now={NOW} />)
    const el = screen.getByText('closes in 6d')
    expect(el).toHaveClass('text-danger')
  })

  it('renders Empty when the closing date is unknown', () => {
    render(<Deadline closesAt={null} now={NOW} />)
    expect(screen.getByLabelText('not specified')).toBeInTheDocument()
  })

  it('renders Empty once the deadline has already elapsed', () => {
    render(<Deadline closesAt="2026-09-01T09:00:00Z" now={NOW} />)
    expect(screen.getByLabelText('not specified')).toBeInTheDocument()
  })
})
