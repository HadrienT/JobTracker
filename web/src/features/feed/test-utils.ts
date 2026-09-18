/**
 * jsdom has no layout engine: every element's `getBoundingClientRect()` reports
 * zero size, which makes TanStack Virtual think the scroll container has no
 * room and render nothing. Tests that need a realistic viewport call this to
 * give every element a fixed, non-zero size for the duration of the test.
 */
export function mockViewportDimensions(width: number, height: number): () => void {
  // eslint-disable-next-line @typescript-eslint/unbound-method -- stored only to be reassigned back verbatim, never called
  const originalGetBoundingClientRect = Element.prototype.getBoundingClientRect
  const originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')
  const originalOffsetWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth')

  Element.prototype.getBoundingClientRect = function boundingClientRect() {
    return {
      width,
      height,
      top: 0,
      left: 0,
      right: width,
      bottom: height,
      x: 0,
      y: 0,
      toJSON() {
        return {}
      },
    }
  }
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: height })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: width })

  return () => {
    Element.prototype.getBoundingClientRect = originalGetBoundingClientRect
    if (originalOffsetHeight) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight)
    if (originalOffsetWidth) Object.defineProperty(HTMLElement.prototype, 'offsetWidth', originalOffsetWidth)
  }
}
