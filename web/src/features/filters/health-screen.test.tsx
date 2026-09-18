import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { axe } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { HealthScreen } from '@/features/filters/health-screen'
import { HEALTH } from '@/mocks/data'

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <HealthScreen />
    </QueryClientProvider>,
  )
}

describe('HealthScreen', () => {
  it('renders GET /health with no serious axe violations', async () => {
    const firstSource = HEALTH.sources[0]
    if (!firstSource) throw new Error('fixture is empty')
    const { container } = renderScreen()
    expect(await screen.findByText(firstSource.source)).toBeInTheDocument()
    expect(screen.getByText('Fresh')).toBeInTheDocument()
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
