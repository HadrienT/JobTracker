import { useState } from 'react'
import { useCompanies } from '@/api/queries'
import { SECTOR_OPTIONS } from '@/features/filters/defaults'
import { cn } from '@/shared/lib/cn'

/**
 * The registry, not a job board (blueprint/wp/WP11-web-filters.md §5): what it's
 * actually for is spotting a company at zero postings for weeks — that's
 * almost always a broken ATS token, not a hiring freeze.
 */
export function CompaniesScreen() {
  const [sector, setSector] = useState<string | null>(null)
  const companies = useCompanies(sector ? { sector } : {})

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-4">
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">Companies</h1>
        <label className="ml-auto flex items-center gap-2 text-sm text-text-secondary">
          Sector
          <select
            value={sector ?? ''}
            onChange={(event) => {
              setSector(event.target.value === '' ? null : event.target.value)
            }}
            className="rounded-md border border-border bg-surface px-2 py-1 text-text-primary"
          >
            <option value="">All</option>
            {SECTOR_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {companies.isPending && <p className="text-sm text-text-tertiary">Loading…</p>}
      {companies.isError && <p className="text-sm text-danger">Couldn&apos;t load the registry.</p>}

      {companies.data && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
              <th className="py-2 pr-4">Company</th>
              <th className="py-2 pr-4">Country</th>
              <th className="py-2 pr-4">Sector</th>
              <th className="py-2 pr-4">ATS</th>
              <th className="py-2 pr-4">Active postings</th>
              <th className="py-2 pr-4">Last successful collect</th>
              <th className="py-2 pr-4">Enabled</th>
            </tr>
          </thead>
          <tbody>
            {companies.data.map((company) => {
              const muted = company.enabled && company.postings_count === 0
              return (
                <tr key={company.company_slug} className={cn('border-b border-border/60', muted && 'bg-danger/5')}>
                  <td className="py-2 pr-4 text-text-primary">{company.company_name}</td>
                  <td className="py-2 pr-4 text-text-secondary">{company.hq_country}</td>
                  <td className="py-2 pr-4 text-text-secondary">{company.sector}</td>
                  <td className="py-2 pr-4 text-text-secondary">{company.source}</td>
                  <td className={cn('py-2 pr-4 font-tabular', muted ? 'text-danger' : 'text-text-primary')}>
                    {company.postings_count}
                    {muted && <span className="ml-1 text-xs">— possibly a broken token</span>}
                  </td>
                  <td className="py-2 pr-4 text-text-secondary">
                    {company.last_ok_at ? new Date(company.last_ok_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="py-2 pr-4 text-text-secondary">{company.enabled ? 'yes' : 'no'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
