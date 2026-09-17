import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { useTheme } from '@/app/theme-context'
import { ThemeProvider } from '@/app/theme-provider'

function ToggleButton() {
  const { theme, toggleTheme } = useTheme()
  return (
    <button type="button" onClick={toggleTheme}>
      {theme}
    </button>
  )
}

describe('ThemeProvider', () => {
  it('defaults to dark and toggles to light, reflecting it on <html data-theme>', async () => {
    const user = userEvent.setup()
    render(
      <ThemeProvider>
        <ToggleButton />
      </ThemeProvider>,
    )

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    await user.click(screen.getByRole('button', { name: 'dark' }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(screen.getByRole('button', { name: 'light' })).toBeInTheDocument()
  })
})
