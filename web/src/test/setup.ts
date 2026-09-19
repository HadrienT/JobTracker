import '@testing-library/jest-dom/vitest'
import { toHaveNoViolations } from 'jest-axe'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import { resetTracking } from '@/mocks/handlers'
import { server } from '@/mocks/server'

expect.extend(toHaveNoViolations)

// The mock API filters 2 000 fixtures per request; on a busy machine (a build, the LLM, a
// container) the default 1 s is a coin flip. A test that waits longer costs nothing when it passes.
configure({ asyncUtilTimeout: 8000 })

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetTracking()
})

afterAll(() => {
  server.close()
})
