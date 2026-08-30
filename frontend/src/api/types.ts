/**
 * Mirrors the Pydantic response models in app/api/schemas.py.
 *
 * Note what is absent: there is no reasoning, thinking or analysis field
 * anywhere in this file, because the API never emits one. The client cannot
 * render internal model deliberation because it is never given any.
 */

export interface ConfidenceCheck {
  name: string
  passed: boolean
  detail: string
}

export interface Confidence {
  score: number
  level: 'high' | 'medium' | 'low'
  checks: ConfidenceCheck[]
  warnings: string[]
}

export interface GenerationInfo {
  provider: string
  model: string
  latency_ms: number
  completion_tokens: number
  reasoning_suppressed: boolean
}

export type ChartType =
  | 'line'
  | 'bar'
  | 'horizontal_bar'
  | 'pie'
  | 'scatter'
  | 'kpi'
  | 'table'

export type Cell = string | number | boolean | null
export type Row = Record<string, Cell>

export interface PlotlyFigure {
  data?: unknown[]
  layout?: Record<string, unknown>
  /** KPI "figures" are plain value maps rather than Plotly traces. */
  type?: string
  title?: string
  values?: Record<string, string>
}

export interface QueryResponse {
  question: string
  sql: string
  data: Row[]
  columns: string[]
  row_count: number
  chart_type: ChartType
  chart_json: PlotlyFigure | null
  insight: string
  confidence: Confidence
  execution_time_ms: number
  retry_count: number
  warnings: string[]
  session_id: string
  generation: GenerationInfo | null
}

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  llm: 'connected' | 'disconnected'
  provider: string
  model: string
  detail: string
  schema_status: string
  reasoning_suppression: 'enabled'
}

export interface MetricsStats {
  total_queries: number
  success_rate: number
  avg_latency_ms: number
  avg_confidence: number
  queries_today: number
  total_retries: number
}

export interface MetricsResponse {
  stats: MetricsStats
  recent: Array<{
    question: string
    success: boolean
    execution_time_ms: number
    confidence_score: number
    row_count: number
    timestamp: string
    error: string | null
  }>
}

export interface SuggestionsResponse {
  suggestions: string[]
  source: 'model' | 'fallback'
}

export interface DashboardKpis {
  total_revenue: number
  total_profit: number
  total_orders: number
  unique_customers: number
  avg_order_value: number
}

export interface DashboardResponse {
  kpis: DashboardKpis
  panels: Record<string, Row[]>
  generated_in_ms: number
}

export interface ApiErrorBody {
  error: string
  message: string
  details?: unknown
  sql?: string
  retry_count?: number
}
