import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { describe, expect, it, vi } from 'vitest'
import { TopNav } from '@/app/top-nav'

describe('TopNav', () => {
  it('marks the current route and has no serious axe violations', async () => {
    const { container } = render(<TopNav route="companies" navigate={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Companies' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Feed' })).not.toHaveAttribute('aria-current')
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('navigates when a link is clicked', async () => {
    const user = userEvent.setup()
    const navigate = vi.fn()
    render(<TopNav route="feed" navigate={navigate} />)
    await user.click(screen.getByRole('button', { name: 'Health' }))
    expect(navigate).toHaveBeenCalledWith('/health')
  })
})
