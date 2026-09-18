import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import type { PostingsFilter } from '@/api/queries'
import { DEFAULT_FILTER, DEFAULT_VISA, VISA_OPTIONS } from '@/features/filters/defaults'
import { FiltersPanel } from '@/features/filters/filters-panel'

function Harness({ initialFilter = DEFAULT_FILTER }: { initialFilter?: PostingsFilter }) {
  const [filter, setFilter] = useState<PostingsFilter>(initialFilter)
  return (
    <FiltersPanel
      filter={filter}
      onChange={(patch) => {
        setFilter((current) => ({ ...current, ...patch }))
      }}
      onReset={() => {
        setFilter(DEFAULT_FILTER)
      }}
    />
  )
}

function renderPanel(initialFilter?: PostingsFilter) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness initialFilter={initialFilter} />
    </QueryClientProvider>,
  )
}

describe('FiltersPanel', () => {
  it('has no serious axe violations', async () => {
    const { container } = renderPanel()
    await screen.findByRole('checkbox', { name: /GB/ })
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('invariant I6: checking one country leaves the others selectable with their own counts', async () => {
    const user = userEvent.setup()
    renderPanel()
    const usBefore = await screen.findByRole('checkbox', { name: /^US/ })
    const usLabelTextBefore = usBefore.closest('label')?.textContent

    await user.click(screen.getByRole('checkbox', { name: /^GB/ }))
    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /^GB/ })).toBeChecked()
    })

    const usAfter = screen.getByRole('checkbox', { name: /^US/ })
    expect(usAfter).not.toBeDisabled()
    expect(usAfter.closest('label')?.textContent).toBe(usLabelTextBefore)
  })

  it('renders a zero-count option greyed out, never hidden', async () => {
    renderPanel({ ...DEFAULT_FILTER, companies: ['jane_street'] })
    const bankLabel = (await screen.findByText('Bank')).closest('label')
    if (!bankLabel) throw new Error('Bank label not rendered')
    expect(bankLabel.className).toContain('opacity-50')
    expect(within(bankLabel).getByRole('checkbox')).not.toBeDisabled()
  })

  it('Reset returns every dimension to its default, visa included', async () => {
    const user = userEvent.setup()
    renderPanel({ ...DEFAULT_FILTER, visa: ['no'], countries: ['GB'] })
    expect(screen.getByRole('checkbox', { name: /^GB/ })).toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Reset' }))

    await waitFor(() => {
      expect(screen.getByRole('checkbox', { name: /^GB/ })).not.toBeChecked()
    })
    for (const value of DEFAULT_VISA) {
      const option = VISA_OPTIONS.find((o) => o.value === value)
      if (!option) throw new Error(`unreachable: ${value} is not a VISA_OPTIONS value`)
      expect(screen.getByRole('checkbox', { name: option.label })).toBeChecked()
    }
  })

  it('the Reset button is disabled when the filter is already at its defaults', () => {
    renderPanel()
    expect(screen.getByRole('button', { name: 'Reset' })).toBeDisabled()
  })
})
