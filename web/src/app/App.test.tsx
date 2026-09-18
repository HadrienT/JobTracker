import { render, screen } from '@testing-library/react'
import { axe } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { App } from '@/app/App'

describe('App', () => {
  it('renders the feed screen with no serious axe violations', async () => {
    const { container } = render(<App />)
    await screen.findByRole('grid', { name: 'Job postings' })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
