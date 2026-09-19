import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SavedViews } from '@/features/filters/saved-views-menu'
import { deleteView, loadViews, saveView } from '@/features/filters/saved-views'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  window.history.pushState(null, '', '/')
  vi.restoreAllMocks()
})

describe('saved views storage', () => {
  it('starts empty', () => {
    expect(loadViews()).toEqual([])
  })

  it('keeps the newest first and replaces a view saved under the same name', () => {
    saveView('London juniors', '?countries=GB')
    saveView('Python', '?tech_any=python')
    saveView('London juniors', '?countries=GB&seniorities=junior')

    expect(loadViews()).toEqual([
      { name: 'London juniors', search: '?countries=GB&seniorities=junior' },
      { name: 'Python', search: '?tech_any=python' },
    ])
  })

  it('ignores an empty name', () => {
    saveView('   ', '?countries=GB')
    expect(loadViews()).toEqual([])
  })

  it('deletes by name', () => {
    saveView('a', '?x=1')
    saveView('b', '?x=2')
    expect(deleteView('a')).toEqual([{ name: 'b', search: '?x=2' }])
  })

  it('survives a corrupted or blocked store', () => {
    localStorage.setItem('jobtracker.savedViews', '{not json')
    expect(loadViews()).toEqual([])
    localStorage.setItem('jobtracker.savedViews', JSON.stringify([{ name: 1 }, { name: 'ok', search: '?a=1' }]))
    expect(loadViews()).toEqual([{ name: 'ok', search: '?a=1' }])
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(loadViews()).toEqual([])
  })
})

describe('SavedViews menu', () => {
  it('saves the current search under a name and applies it later', async () => {
    const user = userEvent.setup()
    window.history.pushState(null, '', '/?countries=GB&tech_any=python')
    render(<SavedViews />)

    await user.click(screen.getByText('Views'))
    await user.type(screen.getByRole('textbox', { name: 'Name for this view' }), 'London Python')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    window.history.pushState(null, '', '/') // filters cleared
    const popstate = vi.fn()
    window.addEventListener('popstate', popstate)
    await user.click(within(screen.getByRole('list', { name: 'Saved views' })).getByText('London Python'))

    expect(window.location.search).toBe('?countries=GB&tech_any=python')
    expect(popstate).toHaveBeenCalled() // the screens are told the URL moved
    window.removeEventListener('popstate', popstate)
  })

  it('will not save without a name', async () => {
    const user = userEvent.setup()
    render(<SavedViews />)
    await user.click(screen.getByText('Views'))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('deletes a view', async () => {
    const user = userEvent.setup()
    saveView('gone soon', '?a=1')
    render(<SavedViews />)
    await user.click(screen.getByText('Views'))

    await user.click(screen.getByRole('button', { name: 'Delete view gone soon' }))

    expect(screen.getByText('No saved views yet.')).toBeInTheDocument()
    expect(loadViews()).toEqual([])
  })

  it('leaves the detail URL for the feed when a view is applied from it', async () => {
    const user = userEvent.setup()
    saveView('mine', '?countries=US')
    window.history.pushState(null, '', '/p/abc')
    render(<SavedViews />)
    await user.click(screen.getByText('Views'))

    await user.click(screen.getByText('mine'))

    expect(window.location.pathname + window.location.search).toBe('/?countries=US')
  })
})
