import { useEffect, useMemo, useRef } from 'react'

import type { DashboardResponse, Row } from '../api/types'
import { formatCurrency, formatNumber } from '../lib/format'
import { loadPlotly } from '../lib/plotly'
import { AlertIcon, RefreshIcon } from './Icons'

interface DashboardViewProps {
  data: DashboardResponse | null
  isLoading: boolean
  error: string | null
  onReload: () => void
}

const PALETTE = ['#6366f1', '#22d3ee', '#34d399', '#f59e0b', '#f472b6', '#a78bfa']

export default function DashboardView({
  data,
  isLoading,
  error,
  onReload,
}: DashboardViewProps) {
  if (error) {
    return (
      <div className="error-card error-card--block" role="alert">
        <AlertIcon />
        <div>
          <p className="error-card__title">{error}</p>
          <p className="error-card__hint">
            The dashboard reads directly from the database through the API.
            Check that the backend is running and the database is reachable.
          </p>
          <button type="button" className="button button--ghost" onClick={onReload}>
            <RefreshIcon />
            <span>Try again</span>
          </button>
        </div>
      </div>
    )
  }

  if (isLoading || !data) {
    return (
      <div className="dashboard">
        <div className="kpi-row">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="skeleton skeleton--kpi" />
          ))}
        </div>
        <div className="panel-grid">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="skeleton skeleton--panel" />
          ))}
        </div>
      </div>
    )
  }

  const { kpis, panels } = data

  return (
    <div className="dashboard">
      <div className="dashboard__bar">
        <p className="muted">
          Built server-side in {Math.round(data.generated_in_ms)} ms
        </p>
        <button type="button" className="button button--ghost" onClick={onReload}>
          <RefreshIcon />
          <span>Refresh</span>
        </button>
      </div>

      <div className="kpi-row">
        <Kpi label="Total revenue" value={formatCurrency(kpis.total_revenue)} />
        <Kpi label="Total profit" value={formatCurrency(kpis.total_profit)} />
        <Kpi label="Orders" value={formatNumber(kpis.total_orders)} />
        <Kpi label="Customers" value={formatNumber(kpis.unique_customers)} />
        <Kpi label="Avg order value" value={formatCurrency(kpis.avg_order_value)} />
      </div>

      <div className="panel-grid">
        <Panel title="Monthly revenue and profit">
          <Figure
            traces={buildMonthlyTraces(panels.monthly_trend ?? [])}
            name="Monthly revenue and profit"
          />
        </Panel>

        <Panel title="Revenue and profit by region">
          <Figure
            traces={buildGroupedBars(panels.by_region ?? [], 'region_name', [
              'revenue',
              'profit',
            ])}
            name="Revenue and profit by region"
            barmode="group"
          />
        </Panel>

        <Panel title="Revenue by customer segment">
          <Figure
            traces={buildDonut(panels.by_segment ?? [], 'segment', 'revenue')}
            name="Revenue by customer segment"
          />
        </Panel>

        <Panel title="Top 10 products by revenue">
          <Figure
            traces={buildHorizontalBars(panels.top_products ?? [], 'product_name', 'revenue')}
            name="Top 10 products by revenue"
            height={420}
          />
        </Panel>

        <Panel title="Loyalty tiers">
          <Figure
            traces={buildGroupedBars(panels.by_loyalty_tier ?? [], 'loyalty_tier', [
              'customers',
            ])}
            name="Customers by loyalty tier"
            barmode="group"
          />
        </Panel>

        <Panel title="Quarterly revenue and profit">
          <Figure
            traces={buildQuarterlyTraces(panels.quarterly ?? [])}
            name="Quarterly revenue and profit"
            barmode="group"
          />
        </Panel>
      </div>
    </div>
  )
}

// ── Building blocks ───────────────────────────────────────────

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi">
      <span className="kpi__value">{value}</span>
      <span className="kpi__label">{label}</span>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h2 className="panel__title">{title}</h2>
      {children}
    </section>
  )
}

interface FigureProps {
  traces: Record<string, unknown>[]
  name: string
  barmode?: string
  height?: number
}

function Figure({ traces, name, barmode, height = 320 }: FigureProps) {
  const container = useRef<HTMLDivElement>(null)
  const layout = useMemo(
    () => ({
      autosize: true,
      height,
      barmode,
      // automargin lets Plotly grow the gutter for long category labels
      // (product names in the horizontal bar panel) instead of clipping them.
      margin: { l: 48, r: 20, t: 12, b: 44, autoexpand: true },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#a8b3cf', family: 'Inter, system-ui, sans-serif', size: 12 },
      xaxis: { gridcolor: 'rgba(148,163,184,0.14)', zeroline: false, automargin: true },
      yaxis: { gridcolor: 'rgba(148,163,184,0.14)', zeroline: false, automargin: true },
      legend: { orientation: 'h', y: -0.22, font: { size: 11 } },
      showlegend: traces.length > 1,
    }),
    [barmode, height, traces.length],
  )

  useEffect(() => {
    const node = container.current
    if (!node || traces.length === 0) return

    let cancelled = false
    let cleanup: (() => void) | undefined

    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !node.isConnected) return
        return Plotly.react(node, traces as never[], layout, {
          displayModeBar: false,
          responsive: true,
        }).then(() => {
          if (cancelled) return
          const observer = new ResizeObserver(() => {
            if (node.isConnected) Plotly.Plots.resize(node)
          })
          observer.observe(node)
          cleanup = () => {
            observer.disconnect()
            Plotly.purge(node)
          }
        })
      })
      .catch(() => undefined)

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [layout, traces])

  if (traces.length === 0) {
    return <p className="muted">No data available for this panel.</p>
  }

  return (
    <div
      ref={container}
      className="chart"
      role="img"
      aria-label={'Chart: ' + name}
      style={{ minHeight: height }}
    />
  )
}

// ── Trace builders ────────────────────────────────────────────

const num = (value: unknown): number => (typeof value === 'number' ? value : Number(value) || 0)
const str = (value: unknown): string => (value === null || value === undefined ? '' : String(value))

function buildMonthlyTraces(rows: Row[]): Record<string, unknown>[] {
  if (rows.length === 0) return []
  const years = Array.from(new Set(rows.map((r) => str(r.year)))).sort()

  return years.map((year, index) => {
    const yearRows = rows.filter((r) => str(r.year) === year)
    return {
      type: 'scatter',
      mode: 'lines+markers',
      name: year,
      x: yearRows.map((r) => str(r.month_name).slice(0, 3)),
      y: yearRows.map((r) => num(r.revenue)),
      line: { color: PALETTE[index % PALETTE.length], width: 2.5, shape: 'spline' },
      marker: { size: 6 },
      hovertemplate: '%{x} ' + year + '<br>Revenue: %{y:$,.0f}<extra></extra>',
    }
  })
}

function buildGroupedBars(
  rows: Row[],
  categoryKey: string,
  valueKeys: string[],
): Record<string, unknown>[] {
  if (rows.length === 0) return []
  return valueKeys.map((key, index) => ({
    type: 'bar',
    name: key.charAt(0).toUpperCase() + key.slice(1),
    x: rows.map((r) => str(r[categoryKey])),
    y: rows.map((r) => num(r[key])),
    marker: { color: PALETTE[index % PALETTE.length] },
    hovertemplate: '%{x}<br>%{y:,.0f}<extra></extra>',
  }))
}

function buildHorizontalBars(
  rows: Row[],
  categoryKey: string,
  valueKey: string,
): Record<string, unknown>[] {
  if (rows.length === 0) return []
  const ordered = [...rows].reverse()
  return [
    {
      type: 'bar',
      orientation: 'h',
      x: ordered.map((r) => num(r[valueKey])),
      y: ordered.map((r) => str(r[categoryKey])),
      marker: { color: PALETTE[0] },
      hovertemplate: '%{y}<br>%{x:$,.0f}<extra></extra>',
    },
  ]
}

function buildDonut(
  rows: Row[],
  labelKey: string,
  valueKey: string,
): Record<string, unknown>[] {
  if (rows.length === 0) return []
  return [
    {
      type: 'pie',
      hole: 0.55,
      labels: rows.map((r) => str(r[labelKey])),
      values: rows.map((r) => num(r[valueKey])),
      marker: { colors: PALETTE.slice(0, rows.length) },
      textinfo: 'label+percent',
      hovertemplate: '%{label}<br>%{value:$,.0f}<extra></extra>',
    },
  ]
}

function buildQuarterlyTraces(rows: Row[]): Record<string, unknown>[] {
  if (rows.length === 0) return []
  const labels = rows.map((r) => 'Q' + str(r.quarter) + ' ' + str(r.year))
  return [
    {
      type: 'bar',
      name: 'Revenue',
      x: labels,
      y: rows.map((r) => num(r.revenue)),
      marker: { color: PALETTE[0] },
      hovertemplate: '%{x}<br>Revenue: %{y:$,.0f}<extra></extra>',
    },
    {
      type: 'bar',
      name: 'Profit',
      x: labels,
      y: rows.map((r) => num(r.profit)),
      marker: { color: PALETTE[2] },
      hovertemplate: '%{x}<br>Profit: %{y:$,.0f}<extra></extra>',
    },
  ]
}
