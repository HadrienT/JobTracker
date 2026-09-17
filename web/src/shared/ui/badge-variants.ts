import { cva } from 'class-variance-authority'

export const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-surface-elevated text-text-secondary',
        strong: 'border-tier-strong/40 bg-tier-strong/10 text-tier-strong',
        possible: 'border-tier-possible/40 bg-tier-possible/10 text-tier-possible',
        stretch: 'border-tier-stretch/40 bg-tier-stretch/10 text-tier-stretch',
        rejected: 'border-tier-rejected/40 bg-tier-rejected/10 text-tier-rejected',
        visaSponsors: 'border-visa-sponsors/40 bg-visa-sponsors/10 text-visa-sponsors',
        visaUnknown: 'border-visa-unknown/40 bg-visa-unknown/10 text-visa-unknown',
        visaNo: 'border-visa-no/40 bg-visa-no/10 text-visa-no',
      },
    },
    defaultVariants: {
      tone: 'neutral',
    },
  },
)
