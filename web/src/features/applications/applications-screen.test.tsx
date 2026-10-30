import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { axe } from 'jest-axe'
import { afterEach, describe, expect, it } from 'vitest'
import { ApplicationsScreen } from '@/features/applications/applications-screen'

function renderScreen(path = '/applications') {
  window.history.pushState(null, '', path)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ApplicationsScreen />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('ApplicationsScreen', () => {
  it('opens on what is still open, with the numbers of everything — no serious axe violations', async () => {
    const { container } = renderScreen()
    expect(await screen.findByText('Northwind Capital')).toBeInTheDocument()
    // abandoned (no news 5+ months) and rejected applications are not "open"
    expect(screen.queryByText('Contoso Trading')).not.toBeInTheDocument()
    expect(screen.queryByText('Fabrikam Securities')).not.toBeInTheDocument()
    const summary = screen.getByRole('region', { name: 'Summary' })
    expect(within(summary).getByText('Applications').nextSibling).toHaveTextContent('4')
    expect(within(summary).getByText('No news 5+ months').nextSibling).toHaveTextContent('1')
    expect(await axe(container)).toHaveNoViolations()
  })

  it('flags the rows that carry a note, whose status may not tell everything', async () => {
    renderScreen()
    const flagged = (await screen.findByText('Tailspin Research')).closest('tr')
    expect(flagged).not.toBeNull()
    expect(within(flagged as HTMLElement).getByLabelText('Note: referral')).toHaveAttribute('title', 'referral')
    const plain = screen.getByText('Northwind Capital').closest('tr')
    expect(within(plain as HTMLElement).queryByText('note')).not.toBeInTheDocument()
  })

  it('switches views and searches, and keeps them in the URL', async () => {
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('Northwind Capital')
    await user.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getAllByTestId('application-row')).toHaveLength(4)
    expect(screen.getByText('after interview')).toBeInTheDocument()
    await user.type(screen.getByRole('searchbox', { name: 'Search applications' }), 'contoso')
    expect(screen.getAllByTestId('application-row')).toHaveLength(1)
    expect(screen.getByText('no news 5+ mo')).toBeInTheDocument()
    await waitFor(() => {
      expect(window.location.search).toBe('?view=all&q=contoso')
    })
  })

  it('colours each location by country, and the legend filters on it', async () => {
    const user = userEvent.setup()
    renderScreen('/applications?view=all')
    await screen.findByText('Northwind Capital')
    const legend = screen.getByRole('group', { name: 'Countries' })
    // the four fixtures: UK, Switzerland, USA, Singapore
    expect(within(legend).getAllByRole('button')).toHaveLength(4)
    const row = screen.getByText('CH (Zurich)').closest('td')
    expect(row?.className).toContain('bg-country-ch/15')
    await user.click(within(legend).getByRole('button', { name: 'Switzerland: 1' }))
    expect(screen.getAllByTestId('application-row')).toHaveLength(1)
    expect(screen.getByText('Contoso Trading')).toBeInTheDocument()
    await waitFor(() => {
      expect(window.location.search).toBe('?view=all&country=CH')
    })
    await user.click(screen.getByRole('button', { name: 'All countries' }))
    expect(screen.getAllByTestId('application-row')).toHaveLength(4)
  })

  it('records a step from the detail panel, which lands in the history', async () => {
    const user = userEvent.setup()
    renderScreen()
    await user.click(await screen.findByRole('button', { name: 'Quantitative Developer' }))
    const panel = await screen.findByRole('dialog')
    expect(window.location.pathname).toBe('/applications/p/app-open')
    expect(await within(panel).findByRole('link', { name: 'CV.pdf' })).toHaveAttribute(
      'href',
      '/applications/app-open/files/Northwind%20Capital/Quant%20Dev%20London/CV.pdf',
    )
    await user.selectOptions(within(panel).getByRole('combobox', { name: 'New status' }), 'interview')
    await user.click(within(panel).getByRole('button', { name: 'Record' }))
    const history = within(panel).getByRole('list', { name: 'History' })
    await waitFor(() => {
      expect(within(history).getAllByRole('listitem')).toHaveLength(2)
    })
    await user.keyboard('{Escape}')
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/applications')
  })

  it('types in an application, then shows it', async () => {
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('Northwind Capital')
    await user.click(screen.getByRole('button', { name: 'New application' }))
    const dialog = screen.getByRole('dialog', { name: 'New application' })
    await user.type(within(dialog).getByRole('textbox', { name: 'Company *' }), 'Woodgrove Bank')
    await user.type(within(dialog).getByRole('textbox', { name: 'Job title *' }), 'Quant Analyst')
    await user.type(within(dialog).getByRole('textbox', { name: /Offer text/ }), 'We need a quant.')
    await user.click(within(dialog).getByRole('button', { name: 'Record the application' }))
    const panel = await screen.findByRole('dialog', { name: 'Quant Analyst' })
    expect(within(panel).getByRole('link', { name: 'offer.pdf' })).toBeInTheDocument()
    expect(await screen.findByText('Woodgrove Bank', { selector: 'td' })).toBeInTheDocument()
  })

  it('deletes only after a confirmation', async () => {
    const user = userEvent.setup()
    renderScreen('/applications/p/app-by-hand')
    const panel = await screen.findByRole('dialog', {
      name: 'Junior Quant Researcher',
    })
    await user.click(within(panel).getByRole('button', { name: 'Delete application…' }))
    await user.click(within(panel).getByRole('button', { name: 'Delete for good' }))
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(screen.queryByText('Tailspin Research')).not.toBeInTheDocument()
  })

  it('shows the CV sent, and finds the applications without one', async () => {
    const user = userEvent.setup()
    renderScreen('/applications?view=all')
    await screen.findByText('Northwind Capital')
    const row = screen.getByText('Northwind Capital').closest('tr') as HTMLElement
    expect(await within(row).findByText('v2')).toBeInTheDocument()
    const assumed = screen.getByText('Tailspin Research').closest('tr') as HTMLElement
    expect(within(assumed).getByTitle('Assumed, not confirmed')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'No CV (1)' }))
    expect(screen.getAllByTestId('application-row')).toHaveLength(1)
    expect(screen.getByText('Contoso Trading')).toBeInTheDocument()
    await waitFor(() => {
      expect(window.location.search).toBe('?view=all&cv=none')
    })
  })

  it('offers the versions, and the CVs written for one offer on demand', async () => {
    const user = userEvent.setup()
    renderScreen('/applications/p/app-open')
    const panel = await screen.findByRole('dialog', { name: 'Quantitative Developer' })
    const section = within(panel).getByRole('region', { name: 'CV' })
    const menu = within(section).getByRole<HTMLSelectElement>('combobox', { name: 'CV used' })
    await waitFor(() => {
      expect(menu).toHaveValue('cv-v2')
    })
    expect(within(section).getByRole('link', { name: 'Preview ↗' })).toHaveAttribute('href', '/cvs/cv-v2/file')
    expect(within(menu).queryByText(/Tailspin/)).not.toBeInTheDocument()
    await user.click(within(section).getByRole('checkbox', { name: /written for one offer/ }))
    expect(within(menu).getByText(/Tailspin/)).toBeInTheDocument()

    await user.selectOptions(menu, 'cv-v1')
    await waitFor(() => {
      expect(menu).toHaveValue('cv-v1')
    })
    await user.selectOptions(menu, '')
    await waitFor(() => {
      expect(menu).toHaveValue('')
    })
  })

  it('confirms a CV that was only assumed', async () => {
    const user = userEvent.setup()
    renderScreen('/applications/p/app-by-hand')
    const panel = await screen.findByRole('dialog', { name: 'Junior Quant Researcher' })
    await user.click(within(panel).getByRole('button', { name: 'Confirm this CV' }))
    await waitFor(() => {
      expect(within(panel).queryByText('Assumed, not confirmed.')).not.toBeInTheDocument()
    })
  })

  it('adds a version and picks it, and refuses what is no PDF', async () => {
    const user = userEvent.setup({ applyAccept: false })
    renderScreen('/applications/p/app-rejected')
    const panel = await screen.findByRole('dialog', { name: 'C++ Developer' })
    const input = within(panel).getByLabelText('Add a CV version')
    await user.upload(input, new File(['<html>'], 'page.pdf', { type: 'application/pdf' }))
    expect(await within(panel).findByText(/not a PDF/)).toBeInTheDocument()

    await user.upload(input, new File(['%PDF-1.5'], 'CV_v3.pdf', { type: 'application/pdf' }))
    await waitFor(() => {
      expect(within(panel).getByRole('combobox', { name: 'CV used' })).toHaveValue('cv-4')
    })
    expect(within(panel).getByRole('textbox', { name: 'CV name' })).toHaveValue('CV_v3')
  })

  it('renames a CV', async () => {
    const user = userEvent.setup()
    renderScreen('/applications/p/app-rejected')
    const panel = await screen.findByRole('dialog', { name: 'C++ Developer' })
    const name = await within(panel).findByRole('textbox', { name: 'CV name' })
    await user.clear(name)
    await user.type(name, 'first version')
    await user.click(within(panel).getByRole('button', { name: 'Rename' }))
    expect(await within(panel).findByRole('option', { name: /first version/ })).toBeInTheDocument()
  })

  it('presets the version in use on a new application', async () => {
    const user = userEvent.setup()
    renderScreen()
    await screen.findByText('Northwind Capital')
    await user.click(screen.getByRole('button', { name: 'New application' }))
    const dialog = screen.getByRole('dialog', { name: 'New application' })
    await waitFor(() => {
      expect(within(dialog).getByRole('combobox', { name: 'CV sent' })).toHaveValue('cv-v2')
    })
  })

  it('tells what became of each version', async () => {
    renderScreen()
    const summary = await screen.findByText('CV versions')
    const table = within(summary.closest('details') as HTMLElement)
    expect(table.getByText('(1 inferred)')).toBeInTheDocument()
  })
})
