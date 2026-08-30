/**
 * Lazily loaded Plotly bundle.
 *
 * Plotly is by far the largest dependency in the app (~1 MB minified). Loading
 * it on demand keeps it out of the initial bundle, so the chat shell paints
 * immediately and the chart library only arrives when there is a chart to draw.
 * The promise is memoised, so concurrent charts share one download.
 */

type PlotlyModule = typeof import('plotly.js-basic-dist-min')['default']

let pending: Promise<PlotlyModule> | null = null

export function loadPlotly(): Promise<PlotlyModule> {
  if (!pending) {
    pending = import('plotly.js-basic-dist-min').then((module) => module.default)
  }
  return pending
}
