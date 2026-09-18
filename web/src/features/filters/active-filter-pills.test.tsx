import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { PostingsFilter } from '@/api/queries'
import { ActiveFilterPills } from '@/features/filters/active-filter-pills'
import { DEFAULT_FILTER } from '@/features/filters/defaults'

function Harness({ initialFilter }: { initialFilter: PostingsFilter }) {
  const [filter, setFilter] = useState(initialFilter)
  return (
    <ActiveFilterPills
      filter={filter}
      onChange={(patch) => {
        setFilter((current) => ({ ...current, ...patch }))
      }}
    />
  )
}

describe('ActiveFilterPills', () => {
  it('renders nothing at the default filter', () => {
    const { container } = render(<Harness initialFilter={DEFAULT_FILTER} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows one pill per active value, and removing it patches just that value away', async () => {
    const user = userEvent.setup()
    render(<Harness initialFilter={{ ...DEFAULT_FILTER, countries: ['GB', 'US'] }} />)

    expect(screen.getByText('GB')).toBeInTheDocument()
    expect(screen.getByText('US')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Remove filter: GB/ }))

    expect(screen.queryByText('GB')).not.toBeInTheDocument()
    expect(screen.getByText('US')).toBeInTheDocument()
  })

  it('summarizes a non-default visa selection as one pill that resets to the default pair', async () => {
    const user = userEvent.setup()
    render(<Harness initialFilter={{ ...DEFAULT_FILTER, visa: ['no'] }} />)

    const pill = screen.getByRole('button', { name: /Visa: no/ })
    expect(pill).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /Remove filter: Visa/ }))
    expect(screen.queryByText(/Visa: no/)).not.toBeInTheDocument()
  })

  it('shows the search query as a removable pill', () => {
    render(<Harness initialFilter={{ ...DEFAULT_FILTER, query: 'quant developer' }} />)
    expect(screen.getByText('“quant developer”')).toBeInTheDocument()
  })
})
