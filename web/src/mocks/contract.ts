/**
 * Domain-facing type aliases shared by `shared/ui` and `mocks/`.
 *
 * The posting-related shapes below are re-exports of `schema.gen.ts` (ADR-005):
 * WP07 has shipped the real API, so nothing here duplicates a type by hand
 * anymore — a drift in the wire contract is a type error here, not a runtime
 * surprise. This file only exists as a stable import path so `shared/ui`
 * doesn't reach into `@/api/schema.gen`'s generated `components["schemas"][...]`
 * indexing directly.
 *
 * `FacetCounts` / `CompanyOut` / `HealthSnapshot` are now real re-exports too
 * (WP11): the WP09 placeholder shapes (bucket arrays, `feed_stale`, ...) are
 * gone — `/facets` returns per-value count dictionaries for exactly seven
 * dimensions (no `visa`/`remote_modes`/`tiers`/`role_families` counts), which
 * is why the filter panel renders those four without a count badge.
 */
import type { components } from '@/api/schema.gen'

type Schemas = components['schemas']

export type Source = Schemas['Source']
export type RoleFamily = Schemas['RoleFamily']
export type Seniority = Schemas['Seniority']
export type VisaStatus = Schemas['VisaStatus']
export type RemoteMode = Schemas['RemoteMode']
export type SalaryPeriod = Schemas['SalaryPeriod']
export type Tier = Schemas['Tier']
export type SortKey = Schemas['SortKey']

export type Location = Schemas['LocationOut']
export type Compensation = Schemas['CompensationOut']
export type Reason = Schemas['Reason']
export type Alias = Schemas['AliasOut']

export type PostingOut = Schemas['PostingOut']
export type PostingDetailOut = Schemas['PostingDetailOut']

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export type FacetCounts = Schemas['FacetCounts']
export type CompanyOut = Schemas['CompanyOut']
export type HealthSnapshot = Schemas['HealthSnapshot']
export type SourceHealth = Schemas['SourceHealth']
export type HealthAlert = Schemas['HealthAlert']
export type FeedHealth = Schemas['FeedHealth']

export const STALE_AFTER_DAYS = 30
