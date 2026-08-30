import type { Confidence } from '../api/types'

const LABELS: Record<Confidence['level'], string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
}

export default function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const failed = confidence.checks.filter((check) => !check.passed)
  const title =
    failed.length > 0
      ? 'Checks that did not pass: ' + failed.map((c) => c.name).join(', ')
      : 'All schema and structure checks passed'

  return (
    <span
      className={'badge badge--' + confidence.level}
      title={title}
      aria-label={LABELS[confidence.level] + ', score ' + confidence.score + ' out of 100'}
    >
      <span className="badge__dot" aria-hidden="true" />
      {LABELS[confidence.level]} · {confidence.score}
    </span>
  )
}
