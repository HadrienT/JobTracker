import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import { LocationCell } from '@/shared/ui/location-cell'
import { TooltipProvider } from '@/shared/ui/tooltip'

function renderWithProvider(ui: ReactElement) {
  return render(<TooltipProvider delayDuration={0}>{ui}</TooltipProvider>)
}

describe('LocationCell', () => {
  it('renders "City COUNTRY" and the remote mode for a single site', () => {
    renderWithProvider(
      <LocationCell
        locations={[{ city: 'Amsterdam', country: 'NL', region: 'emea', remote_mode: 'onsite', raw: 'Amsterdam, NL' }]}
      />,
    )
    expect(screen.getByText('Amsterdam NL')).toBeInTheDocument()
    expect(screen.getByText('onsite')).toBeInTheDocument()
  })

  it('shows a discreet "+2" for multi-site postings', () => {
    renderWithProvider(
      <LocationCell
        locations={[
          { city: 'London', country: 'GB', region: 'emea', remote_mode: 'hybrid', raw: 'London, UK' },
          { city: 'Paris', country: 'FR', region: 'emea', remote_mode: 'hybrid', raw: 'Paris, FR' },
          { city: 'Dublin', country: 'IE', region: 'emea', remote_mode: 'hybrid', raw: 'Dublin, IE' },
        ]}
      />,
    )
    expect(screen.getByText('+2')).toBeInTheDocument()
  })

  it('falls back to the raw string when the location is unresolved', () => {
    renderWithProvider(
      <LocationCell
        locations={[{ city: null, country: null, region: null, remote_mode: 'unknown', raw: 'See job description' }]}
      />,
    )
    expect(screen.getByText('See job description')).toBeInTheDocument()
  })

  it('reveals the raw source string on hover', async () => {
    const user = userEvent.setup()
    renderWithProvider(
      <LocationCell
        locations={[{ city: 'Amsterdam', country: 'NL', region: 'emea', remote_mode: 'onsite', raw: 'Amsterdam, The Netherlands' }]}
      />,
    )
    await user.hover(screen.getByText('Amsterdam NL'))
    expect(await screen.findByText('Amsterdam, The Netherlands')).toBeInTheDocument()
  })
})
