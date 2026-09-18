import { useHealth } from '@/api/queries'
import { cn } from '@/shared/lib/cn'

/** Renders `GET /health` verbatim (blueprint/12-WEB-UI.md §6) — where you look to see which source is degraded. */
export function HealthScreen() {
  const { data, isPending, isError } = useHealth()

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-4">
      <h1 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">Health</h1>

      {isPending && <p className="text-sm text-text-tertiary">Loading…</p>}
      {isError && <p className="text-sm text-danger">Couldn&apos;t load health status.</p>}

      {data && (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Feed</h2>
            <div className="flex items-center gap-4 text-sm">
              <span className={cn('font-tabular', data.feed.stale ? 'text-warning' : 'text-tier-strong')}>
                {data.feed.stale ? 'Stale' : 'Fresh'}
              </span>
              <span className="text-text-secondary">{data.feed.active_postings} active postings</span>
              {data.feed.newest_posting_age_h !== null && (
                <span className="text-text-secondary">Newest posting: {data.feed.newest_posting_age_h}h ago</span>
              )}
            </div>
          </section>

          {data.alerts.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Alerts</h2>
              <ul className="flex flex-col gap-1 text-sm">
                {data.alerts.map((alert, index) => (
                  <li key={`${alert.kind}-${String(index)}`} className="text-danger">
                    {alert.kind}
                    {alert.source && ` — ${alert.source}`} (since {new Date(alert.since).toLocaleString()})
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="flex flex-col gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-text-secondary">Sources</h2>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
                  <th className="py-2 pr-4">Source</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Last run</th>
                  <th className="py-2 pr-4">Boards ok / error</th>
                  <th className="py-2 pr-4">Alert</th>
                </tr>
              </thead>
              <tbody>
                {data.sources.map((source) => (
                  <tr key={source.source} className="border-b border-border/60">
                    <td className="py-2 pr-4 text-text-primary">{source.source}</td>
                    <td
                      className={cn(
                        'py-2 pr-4 font-medium',
                        source.status === 'ok' ? 'text-tier-strong' : 'text-warning',
                      )}
                    >
                      {source.status}
                    </td>
                    <td className="py-2 pr-4 text-text-secondary">
                      {source.last_run_at ? new Date(source.last_run_at).toLocaleString() : '—'}
                    </td>
                    <td className="py-2 pr-4 font-tabular text-text-secondary">
                      {source.boards_ok ?? '—'} / {source.boards_error ?? '—'}
                    </td>
                    <td className="py-2 pr-4 text-danger">{source.alert ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  )
}
