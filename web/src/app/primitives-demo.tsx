import type { ReactNode } from 'react'
import { useTheme } from '@/app/theme-context'
import type { Reason, Tier, VisaStatus } from '@/mocks/contract'
import { POSTINGS, toListItem } from '@/mocks/data'
import { Age } from '@/shared/ui/age'
import { Deadline } from '@/shared/ui/deadline'
import { Empty } from '@/shared/ui/empty'
import { LocationCell } from '@/shared/ui/location-cell'
import { Money } from '@/shared/ui/money'
import { Score } from '@/shared/ui/score'
import { VisaBadge } from '@/shared/ui/visa-badge'

const NOW = new Date('2026-09-17T09:00:00Z')

const VISA_STATES: VisaStatus[] = ['sponsors', 'no', 'unknown']
const TIERS: { tier: Tier; score: number }[] = [
  { tier: 'strong', score: 87 },
  { tier: 'possible', score: 58 },
  { tier: 'stretch', score: 32 },
  { tier: 'rejected', score: 9 },
]
const SAMPLE_REASONS: Reason[] = [
  { code: 'title_match', delta: 25, evidence: 'Quantitative Developer' },
  { code: 'stack_match', delta: 10, evidence: 'C++, Python' },
  { code: 'senior_only', delta: -30, evidence: '8+ years required' },
]

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-border pb-8">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">{title}</h2>
      <div className="flex flex-wrap items-center gap-6">{children}</div>
    </section>
  )
}

function Swatch({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-1">
      <span className="text-xs text-text-tertiary">{label}</span>
      {children}
    </div>
  )
}

export function PrimitivesDemo() {
  const { theme, toggleTheme } = useTheme()
  const sampleRows = POSTINGS.slice(0, 15).map(toListItem)

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-10">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">JobTracker — density primitives</h1>
          <p className="text-sm text-text-secondary">
            Visual reference for the seven primitives of blueprint/wp/WP09-web-foundations.md §4.
          </p>
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text-primary hover:bg-surface-elevated"
        >
          theme: {theme}
        </button>
      </header>

      <Section title="Score">
        {TIERS.map(({ tier, score }) => (
          <Swatch key={tier} label={tier}>
            <Score score={score} tier={tier} reasons={SAMPLE_REASONS} />
          </Swatch>
        ))}
        <Swatch label="no reasons">
          <Score score={50} tier="possible" reasons={[]} />
        </Swatch>
      </Section>

      <Section title="VisaBadge">
        {VISA_STATES.map((status) => (
          <Swatch key={status} label={status}>
            <VisaBadge status={status} />
          </Swatch>
        ))}
      </Section>

      <Section title="Money">
        <Swatch label="range">
          <Money amountMin="60000" amountMax="90000" currency="EUR" period="year" />
        </Swatch>
        <Swatch label="single amount">
          <Money amountMin="450" amountMax="450" currency="GBP" period="day" />
        </Swatch>
        <Swatch label="absent">
          <Money amountMin={null} amountMax={null} currency={null} period={null} />
        </Swatch>
      </Section>

      <Section title="Age">
        <Swatch label="fresh (3d)">
          <Age postedAt={null} firstSeenAt="2026-09-14T09:00:00Z" staleAfterDays={30} now={NOW} />
        </Swatch>
        <Swatch label="stale (>15d, orange)">
          <Age postedAt={null} firstSeenAt="2026-08-20T09:00:00Z" staleAfterDays={30} now={NOW} />
        </Swatch>
        <Swatch label="weeks (2w)">
          <Age postedAt={null} firstSeenAt="2026-09-03T09:00:00Z" staleAfterDays={30} now={NOW} />
        </Swatch>
      </Section>

      <Section title="Deadline">
        <Swatch label="closes in 6d">
          <Deadline closesAt="2026-09-23T09:00:00Z" now={NOW} />
        </Swatch>
        <Swatch label="absent">
          <Deadline closesAt={null} now={NOW} />
        </Swatch>
      </Section>

      <Section title="LocationCell">
        <Swatch label="single site">
          <LocationCell
            locations={[
              { city: 'Amsterdam', country: 'NL', region: 'emea', remote_mode: 'onsite', raw: 'Amsterdam, NL' },
            ]}
          />
        </Swatch>
        <Swatch label="multi-site (+2)">
          <LocationCell
            locations={[
              { city: 'London', country: 'GB', region: 'emea', remote_mode: 'hybrid', raw: 'London, UK' },
              { city: 'Paris', country: 'FR', region: 'emea', remote_mode: 'hybrid', raw: 'Paris, FR' },
              { city: 'Dublin', country: 'IE', region: 'emea', remote_mode: 'hybrid', raw: 'Dublin, IE' },
            ]}
          />
        </Swatch>
        <Swatch label="unresolved">
          <LocationCell
            locations={[
              { city: null, country: null, region: null, remote_mode: 'unknown', raw: 'See job description' },
            ]}
          />
        </Swatch>
      </Section>

      <Section title="Empty">
        <Swatch label="the one rendering of “not stated”">
          <Empty />
        </Swatch>
      </Section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-text-secondary">
          Sample rows from the MSW fixture ({POSTINGS.length} postings total)
        </h2>
        <div className="flex flex-col divide-y divide-border rounded-md border border-border">
          {sampleRows.map((row) => (
            <div key={row.posting_id} className="flex items-center gap-4 px-3 py-2 text-sm">
              <Score score={row.score} tier={row.tier} reasons={[]} />
              <span className="w-72 truncate text-text-primary">{row.title}</span>
              <span className="w-40 truncate text-text-secondary">{row.company_name}</span>
              <LocationCell locations={row.locations} />
              <VisaBadge status={row.visa_sponsorship} />
              <Money
                amountMin={row.compensation.amount_min}
                amountMax={row.compensation.amount_max}
                currency={row.compensation.currency}
                period={row.compensation.period}
              />
              <Age postedAt={row.posted_at} firstSeenAt={row.first_seen_at} staleAfterDays={30} now={NOW} />
              <Deadline closesAt={row.closes_at} now={NOW} />
            </div>
          ))}
        </div>
      </section>
    </main>
  )
}
