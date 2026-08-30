import { useEffect, useRef, useState } from 'react'

import type { PlotlyFigure } from '../api/types'
import { loadPlotly } from '../lib/plotly'

interface PlotlyChartProps {
  figure: PlotlyFigure
  title: string
  height?: number
}

/**
 * Thin imperative wrapper around Plotly.
 *
 * The backend already renders a themed figure, so this component only has to
 * mount it, keep it responsive, and tear it down. Writing the ~40 lines here
 * avoids a React wrapper package whose peer-dependency range would pin the
 * project's React version.
 */
export default function PlotlyChart({ figure, title, height = 380 }: PlotlyChartProps) {
  const container = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    const node = container.current
    if (!node) return

    const data = Array.isArray(figure.data) ? (figure.data as never[]) : []
    if (data.length === 0) {
      setFailed(true)
      return
    }

    const baseLayout = (figure.layout ?? {}) as Record<string, unknown>
    const layout = {
      ...baseLayout,
      autosize: true,
      height,
      // The backend title duplicates the question already shown above the card.
      title: undefined,
      margin: { l: 52, r: 24, t: 16, b: 44, autoexpand: true },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: '#a8b3cf', family: 'Inter, system-ui, sans-serif', size: 12 },
      // Long category labels (product names, cities) must expand the gutter
      // rather than being clipped.
      xaxis: { ...((baseLayout.xaxis as object) ?? {}), automargin: true },
      yaxis: { ...((baseLayout.yaxis as object) ?? {}), automargin: true },
    }

    let cancelled = false
    let cleanup: (() => void) | undefined

    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !node.isConnected) return
        return Plotly.react(node, data, layout, {
          displayModeBar: false,
          displaylogo: false,
          responsive: true,
          modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
        }).then(() => {
          if (cancelled) return
          setFailed(false)
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
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    return () => {
      cancelled = true
      cleanup?.()
    }
  }, [figure, height])

  if (failed) {
    return (
      <p className="chart__fallback">
        This result could not be plotted. The data table below has the full
        result set.
      </p>
    )
  }

  return (
    <div
      ref={container}
      className="chart"
      role="img"
      aria-label={'Chart: ' + title}
      style={{ minHeight: height }}
    />
  )
}
