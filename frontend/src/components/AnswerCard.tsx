import { useMemo, useState } from 'react'

import type { QueryResponse } from '../api/types'
import { formatDuration, humanizeKey } from '../lib/format'
import ConfidenceBadge from './ConfidenceBadge'
import DataTable from './DataTable'
import PlotlyChart from './PlotlyChart'
import { AlertIcon, CheckIcon, CopyIcon } from './Icons'

type Tab = 'chart' | 'data' | 'sql'

const TAB_LABELS: Record<Tab, string> = {
  chart: 'Chart',
  data: 'Data',
  sql: 'SQL',
}

interface AnswerCardProps {
  response: QueryResponse
}

/**
 * Renders one answer.
 *
 * The card shows exactly what the API returned — insight, chart, rows, SQL —
 * and nothing else. There is no code path here that could display model
 * reasoning, because the response type has no field carrying any.
 */
export default function AnswerCard({ response }: AnswerCardProps) {
  const hasChart =
    response.chart_type !== 'table' &&
    response.chart_type !== 'kpi' &&
    Array.isArray(response.chart_json?.data) &&
    (response.chart_json?.data?.length ?? 0) > 0

  const kpiValues = useMemo(() => {
    if (response.chart_type !== 'kpi') return null
    const values = response.chart_json?.values
    if (values && Object.keys(values).length > 0) return values
    const first = response.data[0]
    if (!first) return null
    return Object.fromEntries(
      Object.entries(first).map(([key, value]) => [key, String(value ?? '—')]),
    )
  }, [response])

  const availableTabs = useMemo<Tab[]>(() => {
    const tabs: Tab[] = []
    if (hasChart || kpiValues) tabs.push('chart')
    if (response.data.length > 0) tabs.push('data')
    tabs.push('sql')
    return tabs
  }, [hasChart, kpiValues, response.data.length])

  const [tab, setTab] = useState<Tab>(availableTabs[0])
  const [copied, setCopied] = useState(false)

  const activeTab = availableTabs.includes(tab) ? tab : availableTabs[0]

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(response.sql)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }

  return (
    <article className="answer" aria-label={'Answer to: ' + response.question}>
      <header className="answer__head">
        <ConfidenceBadge confidence={response.confidence} />
        <span className="answer__meta">
          {response.row_count} {response.row_count === 1 ? 'row' : 'rows'}
        </span>
        <span className="answer__meta">
          SQL {formatDuration(response.execution_time_ms)}
        </span>
        {response.generation && (
          <span className="answer__meta">
            Model {formatDuration(response.generation.latency_ms)}
          </span>
        )}
        {response.retry_count > 0 && (
          <span className="answer__meta answer__meta--warn">
            {response.retry_count} auto-correction
            {response.retry_count === 1 ? '' : 's'}
          </span>
        )}
      </header>

      {response.insight && (
        <p className="insight">
          <span className="insight__label">Insight</span>
          <span>{stripMarkdownEmphasis(response.insight)}</span>
        </p>
      )}

      {response.warnings.length > 0 && (
        <ul className="warning-list">
          {response.warnings.map((warning) => (
            <li key={warning}>
              <AlertIcon />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="tabs" role="tablist" aria-label="Result views">
        {availableTabs.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            id={'tab-' + id + '-' + response.session_id + '-' + response.row_count}
            className={'tab' + (activeTab === id ? ' tab--active' : '')}
            aria-selected={activeTab === id}
            onClick={() => setTab(id)}
          >
            {TAB_LABELS[id]}
          </button>
        ))}
      </div>

      <div className="answer__panel" role="tabpanel">
        {activeTab === 'chart' && kpiValues && (
          <div className="kpi-row">
            {Object.entries(kpiValues).map(([label, value]) => (
              <div key={label} className="kpi">
                <span className="kpi__value">{value}</span>
                <span className="kpi__label">{humanizeKey(label)}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'chart' && !kpiValues && hasChart && response.chart_json && (
          <PlotlyChart figure={response.chart_json} title={response.question} />
        )}

        {activeTab === 'data' && (
          <DataTable
            rows={response.data}
            columns={response.columns}
            caption={'Results for: ' + response.question}
          />
        )}

        {activeTab === 'sql' && (
          <div className="sql-block">
            <div className="sql-block__bar">
              <span className="sql-block__label">Generated SQL</span>
              <button type="button" className="button button--tiny" onClick={copySql}>
                {copied ? <CheckIcon /> : <CopyIcon />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
            </div>
            <pre className="sql-block__code">
              <code>{response.sql}</code>
            </pre>
          </div>
        )}
      </div>
    </article>
  )
}

/** The insight generator emits light Markdown emphasis; render it as plain text. */
function stripMarkdownEmphasis(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*(.+?)\*/g, '$1')
}
