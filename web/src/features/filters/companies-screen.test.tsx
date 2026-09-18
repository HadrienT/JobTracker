import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { CompaniesScreen } from '@/features/filters/companies-screen'
import { COMPANIES_OUT } from '@/mocks/data'

function renderScreen() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <CompaniesScreen />
    </QueryClientProvider>,
  )
}

describe('CompaniesScreen', () => {
  it('lists the registry with no serious axe violations', async () => {
    const target = COMPANIES_OUT[0]
    if (!target) throw new Error('fixture is empty')
    const { container } = renderScreen()
    expect(await screen.findByText(target.company_name)).toBeInTheDocument()
    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('filters the registry by sector', async () => {
    const user = userEvent.setup()
    renderScreen()
    await screen.findByRole('table')

    const cryptoCompany = COMPANIES_OUT.find((c) => c.sector === 'crypto')
    const nonCrypto = COMPANIES_OUT.find((c) => c.sector !== 'crypto')
    if (!cryptoCompany || !nonCrypto) throw new Error('fixture needs both a crypto and non-crypto company')

    await user.selectOptions(screen.getByLabelText('Sector'), 'crypto')

    expect(await screen.findByText(cryptoCompany.company_name)).toBeInTheDocument()
    expect(screen.queryByText(nonCrypto.company_name)).not.toBeInTheDocument()
  })
})
