import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '@/features/favorites/toast'
import { useToast } from '@/features/favorites/use-toast'

function ShowButton({ withAction = false, onAction = () => undefined }: { withAction?: boolean; onAction?: () => void }) {
  const toast = useToast()
  return (
    <button
      type="button"
      onClick={() => {
        toast.show('Something happened.', withAction ? { label: 'Undo', onClick: onAction } : undefined)
      }}
    >
      Trigger
    </button>
  )
}

describe('ToastProvider / useToast', () => {
  it('throws when used outside a ToastProvider', () => {
    function Bare() {
      useToast()
      return null
    }
    expect(() => render(<Bare />)).toThrow('useToast must be used within a ToastProvider')
  })

  it('shows a toast message on demand', async () => {
    const user = userEvent.setup()
    render(
      <ToastProvider>
        <ShowButton />
      </ToastProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'Trigger' }))
    expect(await screen.findByText('Something happened.')).toBeInTheDocument()
  })

  it('runs the action and can be dismissed by clicking it', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn()
    render(
      <ToastProvider>
        <ShowButton withAction onAction={onAction} />
      </ToastProvider>,
    )
    await user.click(screen.getByRole('button', { name: 'Trigger' }))
    await user.click(await screen.findByRole('button', { name: 'Undo' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('auto-dismisses after its duration', () => {
    vi.useFakeTimers()
    try {
      render(
        <ToastProvider>
          <ShowButton />
        </ToastProvider>,
      )
      act(() => {
        fireEvent.click(screen.getByRole('button', { name: 'Trigger' }))
      })
      expect(screen.getByText('Something happened.')).toBeInTheDocument()

      act(() => {
        vi.advanceTimersByTime(6000)
      })
      expect(screen.queryByText('Something happened.')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})
