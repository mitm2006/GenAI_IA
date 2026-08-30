import { useState } from 'react'

import type { Row } from '../api/types'
import { formatCell, formatCurrency, humanizeKey, looksLikeCurrency } from '../lib/format'

interface DataTableProps {
  rows: Row[]
  columns: string[]
  /** Rows shown before the "show all" control appears. */
  pageSize?: number
  caption?: string
}

/**
 * Accessible result table.
 *
 * Rendered as a real <table> with a caption and scope-ed headers rather than a
 * Plotly table trace, so screen readers can navigate it and the browser can
 * search it.
 */
export default function DataTable({
  rows,
  columns,
  pageSize = 10,
  caption,
}: DataTableProps) {
  const [expanded, setExpanded] = useState(false)

  if (rows.length === 0) {
    return <p className="muted">This query returned no rows.</p>
  }

  const headers = columns.length > 0 ? columns : Object.keys(rows[0])
  const visible = expanded ? rows : rows.slice(0, pageSize)
  const hidden = rows.length - visible.length

  return (
    <div className="table-block">
      <div className="table-scroll">
        <table className="data-table">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            <tr>
              {headers.map((column) => (
                <th key={column} scope="col">
                  {humanizeKey(column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr key={index}>
                {headers.map((column) => {
                  const value = row[column]
                  const numeric = typeof value === 'number'
                  return (
                    <td key={column} className={numeric ? 'is-numeric' : undefined}>
                      {numeric && looksLikeCurrency(column)
                        ? formatCurrency(value)
                        : formatCell(value)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hidden > 0 && (
        <button
          type="button"
          className="button button--ghost button--full"
          onClick={() => setExpanded(true)}
        >
          Show all {rows.length} rows
        </button>
      )}
      {expanded && rows.length > pageSize && (
        <button
          type="button"
          className="button button--ghost button--full"
          onClick={() => setExpanded(false)}
        >
          Show fewer rows
        </button>
      )}
    </div>
  )
}
