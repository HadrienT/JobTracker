import { geoNaturalEarth1, geoPath } from 'd3-geo'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { feature, mesh } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import worldUrl from 'world-atlas/countries-50m.json?url'
import { useQuery } from '@tanstack/react-query'
import { pinKey, pinRadius, type MapPin } from '@/features/map/pin-utils'
import { cn } from '@/shared/lib/cn'

/** The drawing space. The SVG scales it to its box (`meet`), so nothing here depends on the viewport. */
const WIDTH = 1000
const HEIGHT = 500
const MIN_ZOOM = 1
const MAX_ZOOM = 14
const ZOOM_STEP = 1.6
/** Pixels of pointer travel before a press stops being a click and becomes a pan. */
const DRAG_THRESHOLD_PX = 4

const projection = geoNaturalEarth1().fitExtent(
  [
    [6, 6],
    [WIDTH - 6, HEIGHT - 6],
  ],
  { type: 'Sphere' },
)
const path = geoPath(projection)

interface View {
  k: number
  tx: number
  ty: number
}

const HOME: View = { k: 1, tx: 0, ty: 0 }

/** Keep the world covering the frame: never pan into the void. */
function clampView(view: View): View {
  const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.k))
  return {
    k,
    tx: Math.min(0, Math.max(WIDTH * (1 - k), view.tx)),
    ty: Math.min(0, Math.max(HEIGHT * (1 - k), view.ty)),
  }
}

function zoomAbout(view: View, factor: number, x: number, y: number): View {
  const k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.k * factor))
  const ratio = k / view.k
  return clampView({ k, tx: x - (x - view.tx) * ratio, ty: y - (y - view.ty) * ratio })
}

function pinLabel(pin: MapPin): string {
  const noun = pin.count === 1 ? 'posting' : 'postings'
  return `${pin.city}, ${pin.country} — ${String(pin.count)} ${noun}`
}

interface WorldGeometry {
  land: string
  borders: string
  sphere: string
}

function useWorldGeometry() {
  const query = useQuery({
    queryKey: ['world-topology'] as const,
    queryFn: async () => {
      const response = await fetch(worldUrl)
      if (!response.ok) throw new Error(`world map data: ${String(response.status)}`)
      return (await response.json()) as Topology<{ countries: GeometryCollection }>
    },
    staleTime: Infinity,
    retry: 1,
  })
  const geometry = useMemo<WorldGeometry | null>(() => {
    if (!query.data) return null
    const { countries } = query.data.objects
    return {
      land: path(feature(query.data, countries)) ?? '',
      borders: path(mesh(query.data, countries, (a, b) => a !== b)) ?? '',
      sphere: path({ type: 'Sphere' }) ?? '',
    }
  }, [query.data])
  return { geometry, isError: query.isError, refetch: () => void query.refetch() }
}

interface WorldMapProps {
  pins: readonly MapPin[]
  selectedKey: string | null
  onSelectPin: (pin: MapPin) => void
}

/**
 * A world map drawn in SVG from local data — no tile server: the CSP allows this origin only,
 * and a job board should not phone a map provider for every page view. Wheel / buttons zoom,
 * dragging pans, and each pin is a real button (Tab, Enter, Space) sized by its posting count.
 */
export function WorldMap({ pins, selectedKey, onSelectPin }: WorldMapProps) {
  const { geometry, isError, refetch } = useWorldGeometry()
  const [view, setView] = useState<View>(HOME)
  const svgRef = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null)
  const suppressClick = useRef(false)

  // Biggest first, so a small pin is never buried under a large neighbour.
  const placed = useMemo(
    () =>
      [...pins]
        .sort((a, b) => b.count - a.count)
        .flatMap((pin) => {
          const point = projection([pin.lon, pin.lat])
          return point ? [{ pin, x: point[0], y: point[1] }] : []
        }),
    [pins],
  )

  /** Screen pixels → drawing units, honouring the letterboxing of `xMidYMid meet`. */
  function toDrawing(clientX: number, clientY: number): { x: number; y: number; unitsPerPx: number } {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || rect.height === 0) return { x: WIDTH / 2, y: HEIGHT / 2, unitsPerPx: 1 }
    const scale = Math.min(rect.width / WIDTH, rect.height / HEIGHT)
    const offsetX = (rect.width - WIDTH * scale) / 2
    const offsetY = (rect.height - HEIGHT * scale) / 2
    return {
      x: (clientX - rect.left - offsetX) / scale,
      y: (clientY - rect.top - offsetY) / scale,
      unitsPerPx: 1 / scale,
    }
  }

  // Native listener: React's `onWheel` is passive and cannot stop the page from scrolling.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      const { x, y } = toDrawing(event.clientX, event.clientY)
      const factor = Math.exp(-event.deltaY * 0.0015)
      setView((current) => zoomAbout(current, factor, x, y))
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      svg.removeEventListener('wheel', onWheel)
    }
  }, [])

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return
    drag.current = { x: event.clientX, y: event.clientY, view, moved: false }
    suppressClick.current = false
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const start = drag.current
    if (!start) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (!start.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return
    if (!start.moved) {
      start.moved = true
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    const { unitsPerPx } = toDrawing(event.clientX, event.clientY)
    setView(clampView({ k: start.view.k, tx: start.view.tx + dx * unitsPerPx, ty: start.view.ty + dy * unitsPerPx }))
  }

  function endDrag(event: PointerEvent<SVGSVGElement>) {
    if (drag.current?.moved) {
      suppressClick.current = true
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
    }
    drag.current = null
  }

  function selectPin(pin: MapPin) {
    if (suppressClick.current) return // the press was a pan that happened to end over a pin
    onSelectPin(pin)
  }

  function onPinKeyDown(event: KeyboardEvent<SVGGElement>, pin: MapPin) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelectPin(pin)
    }
  }

  function zoomBy(factor: number) {
    setView((current) => zoomAbout(current, factor, WIDTH / 2, HEIGHT / 2))
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-background">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label="World map of job postings"
        className="h-full w-full touch-none select-none cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <g transform={`translate(${String(view.tx)} ${String(view.ty)}) scale(${String(view.k)})`}>
          {geometry && (
            <>
              <path d={geometry.sphere} className="fill-surface" />
              <path d={geometry.land} className="fill-surface-elevated" />
              <path
                d={geometry.borders}
                className="fill-none stroke-border"
                strokeWidth={0.6}
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
          {placed.map(({ pin, x, y }) => {
            const r = pinRadius(pin.count)
            const selected = pinKey(pin) === selectedKey
            return (
              <g
                key={pinKey(pin)}
                role="button"
                tabIndex={0}
                aria-label={pinLabel(pin)}
                aria-pressed={selected}
                data-testid="map-pin"
                // Constant on-screen size whatever the zoom: counter-scale around the pin.
                transform={`translate(${String(x)} ${String(y)}) scale(${String(1 / view.k)})`}
                className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-text-primary"
                onClick={(event) => {
                  event.stopPropagation()
                  selectPin(pin)
                }}
                onKeyDown={(event) => {
                  onPinKeyDown(event, pin)
                }}
              >
                <title>{pinLabel(pin)}</title>
                <circle
                  r={r}
                  className={cn(
                    'stroke-2 transition-colors',
                    selected ? 'fill-tier-stretch stroke-text-primary' : 'fill-tier-possible stroke-background',
                  )}
                />
                {pin.count > 1 && r >= 10 && (
                  <text
                    textAnchor="middle"
                    dominantBaseline="central"
                    className="pointer-events-none fill-background font-tabular text-[11px] font-semibold"
                  >
                    {pin.count}
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      <div className="absolute right-3 top-3 flex flex-col gap-1">
        <ZoomButton label="Zoom in" onClick={() => { zoomBy(ZOOM_STEP) }}>+</ZoomButton>
        <ZoomButton label="Zoom out" onClick={() => { zoomBy(1 / ZOOM_STEP) }}>−</ZoomButton>
        <ZoomButton label="Reset view" onClick={() => { setView(HOME) }}>⟲</ZoomButton>
      </div>

      {!geometry && !isError && (
        <p className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-text-tertiary">
          Loading map…
        </p>
      )}
      {isError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-sm text-text-secondary">
          <span>Couldn&apos;t load the map data.</span>
          <button
            type="button"
            className="rounded-md border border-border px-2 py-1 text-text-primary hover:bg-surface-elevated"
            onClick={refetch}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  )
}

function ZoomButton({ label, onClick, children }: { label: string; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="h-8 w-8 rounded-md border border-border bg-surface text-base leading-none text-text-primary hover:bg-surface-elevated"
    >
      {children}
    </button>
  )
}
