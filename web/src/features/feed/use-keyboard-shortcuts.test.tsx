import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { useFeedKeyboardShortcuts } from '@/features/feed/use-keyboard-shortcuts'

function Harness({ enabled, onFocusSearch }: { enabled: boolean; onFocusSearch: () => void }) {
  useFeedKeyboardShortcuts(
    {
      onNext: vi.fn(),
      onPrev: vi.fn(),
      onOpen: vi.fn(),
      onOpenSource: vi.fn(),
      onToggleFavorite: vi.fn(),
      onHide: vi.fn(),
      onFocusSearch,
      onEscape: vi.fn(),
    },
    enabled,
  )
  return (
    <div>
      <input aria-label="search" />
    </div>
  )
}

describe('useFeedKeyboardShortcuts', () => {
  it('calls the matching handler for j/k/o/f/h', async () => {
    const user = userEvent.setup()
    const handlers = {
      onNext: vi.fn(),
      onPrev: vi.fn(),
      onOpen: vi.fn(),
      onOpenSource: vi.fn(),
      onToggleFavorite: vi.fn(),
      onHide: vi.fn(),
      onFocusSearch: vi.fn(),
      onEscape: vi.fn(),
    }
    function KeysHarness() {
      useFeedKeyboardShortcuts(handlers, true)
      return <div>feed</div>
    }
    render(<KeysHarness />)

    await user.keyboard('j')
    await user.keyboard('k')
    await user.keyboard('o')
    await user.keyboard('f')
    await user.keyboard('h')

    expect(handlers.onNext).toHaveBeenCalledTimes(1)
    expect(handlers.onPrev).toHaveBeenCalledTimes(1)
    expect(handlers.onOpenSource).toHaveBeenCalledTimes(1)
    expect(handlers.onToggleFavorite).toHaveBeenCalledTimes(1)
    expect(handlers.onHide).toHaveBeenCalledTimes(1)
  })

  it('does nothing when disabled', async () => {
    const user = userEvent.setup()
    const handlers = {
      onNext: vi.fn(),
      onPrev: vi.fn(),
      onOpen: vi.fn(),
      onOpenSource: vi.fn(),
      onToggleFavorite: vi.fn(),
      onHide: vi.fn(),
      onFocusSearch: vi.fn(),
      onEscape: vi.fn(),
    }
    function KeysHarness() {
      useFeedKeyboardShortcuts(handlers, false)
      return <div>feed</div>
    }
    render(<KeysHarness />)
    await user.keyboard('jkofh')
    expect(handlers.onNext).not.toHaveBeenCalled()
    expect(handlers.onToggleFavorite).not.toHaveBeenCalled()
  })

  it('ignores j/k/f/h while typing in a field, but "/" still focuses search from outside it', async () => {
    const user = userEvent.setup()
    const onFocusSearch = vi.fn()
    render(<Harness enabled onFocusSearch={onFocusSearch} />)

    const input = document.querySelector('input')
    if (!input) throw new Error('input not rendered')
    await user.click(input)
    await user.keyboard('f')
    // typed "f" landed in the field, not intercepted as the favorite shortcut
    expect(input).toHaveValue('f')

    await user.click(document.body)
    await user.keyboard('/')
    expect(onFocusSearch).toHaveBeenCalledTimes(1)
  })
})
