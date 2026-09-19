import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { describeValue } from '@/features/feed/describe-value'
import { LlmCorrections } from '@/features/feed/llm-corrections'

const SALARY = {
  field: 'compensation',
  before: { amount_min: '150000', amount_max: '150000', currency: 'USD', period: 'year' },
  after: { amount_min: '150000', amount_max: '350000', currency: 'USD', period: 'year' },
  evidence: 'The base salary range for this role is between $150,000 and $350,000.',
  confidence: 0.9,
  corrected_at: '2026-09-19T15:00:00+00:00',
}

describe('describeValue', () => {
  it('says a single figure once and a range with a dash', () => {
    expect(describeValue('compensation', SALARY.before)).toBe('150000 USD / year')
    expect(describeValue('compensation', SALARY.after)).toBe('150000–350000 USD / year')
  })

  it('says a missing value as "none"', () => {
    expect(describeValue('compensation', null)).toBe('none')
    expect(describeValue('compensation', { amount_min: null, amount_max: null })).toBe('none')
  })

  it('lists locations with their mode when there is one', () => {
    expect(
      describeValue('locations', [
        { city: 'London', country: 'GB', remote_mode: 'hybrid' },
        { city: 'New York', country: 'US', remote_mode: 'unknown' },
      ]),
    ).toBe('London GB hybrid; New York US')
  })

  it('says booleans and scalars plainly', () => {
    expect(describeValue('phd_required', true)).toBe('yes')
    expect(describeValue('visa_sponsorship', 'no')).toBe('no')
  })
})

describe('LlmCorrections', () => {
  it('renders nothing when the LLM changed nothing', () => {
    const { container } = render(<LlmCorrections corrections={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows before, after and the quote for each correction', () => {
    render(<LlmCorrections corrections={[SALARY]} />)

    const section = screen.getByRole('region', { name: 'Corrected by the local LLM' })
    expect(section).toHaveTextContent('Compensation')
    expect(section).toHaveTextContent('150000 USD / year')
    expect(section).toHaveTextContent('150000–350000 USD / year')
    expect(section).toHaveTextContent('between $150,000 and $350,000')
  })
})
