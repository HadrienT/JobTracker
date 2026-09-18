import { useHealth } from '@/api/queries'

/**
 * P3's translation into the UI (blueprint/00-PRIMER.md §2): if collection is
 * broken, the user must see it while scrolling the feed, not by navigating to
 * a separate status page.
 */
export function StaleFeedBanner() {
  const { data } = useHealth()
  if (!data?.feed.stale) return null

  return (
    <div role="status" className="border-b border-warning/40 bg-warning/10 px-4 py-2 text-sm text-warning">
      The feed hasn&apos;t refreshed recently — some postings may be out of date.
    </div>
  )
}
