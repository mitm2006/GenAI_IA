"""
Pre-built dashboard analytics.

The previous Streamlit dashboard opened its own SQLAlchemy engine and issued raw
SQL straight from the presentation layer. In the new architecture the browser has
no database credentials at all: the React dashboard calls ``GET /api/dashboard``
and this module runs the same fixed, parameterless aggregates server-side against
the *read-only* connection, returning plain JSON-safe records.

The SQL here is deliberately dialect-neutral (no ``::numeric`` casts, no
``EXTRACT``) so it runs unchanged on both PostgreSQL and SQLite; rounding is done
in pandas afterwards.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from app.sql.executor import execute_query

# ── Fixed, server-owned queries ───────────────────────────────

_KPI_SQL = """
SELECT SUM(total_amount)          AS total_revenue,
       SUM(profit)                AS total_profit,
       COUNT(*)                   AS total_orders,
       COUNT(DISTINCT customer_id) AS unique_customers,
       AVG(total_amount)          AS avg_order_value
FROM fact_sales
"""

_MONTHLY_TREND_SQL = """
SELECT dd.year, dd.month, dd.month_name,
       SUM(fs.total_amount) AS revenue,
       SUM(fs.profit)       AS profit
FROM fact_sales fs
JOIN dim_date dd ON fs.date_id = dd.date_id
GROUP BY dd.year, dd.month, dd.month_name
ORDER BY dd.year, dd.month
LIMIT 120
"""

_REGION_SQL = """
SELECT r.region_name,
       SUM(fs.total_amount) AS revenue,
       SUM(fs.profit)       AS profit
FROM fact_sales fs
JOIN dim_region r ON fs.region_id = r.region_id
GROUP BY r.region_name
ORDER BY revenue DESC
LIMIT 25
"""

_SEGMENT_SQL = """
SELECT dc.segment,
       COUNT(DISTINCT dc.customer_id) AS customers,
       SUM(fs.total_amount)           AS revenue
FROM fact_sales fs
JOIN dim_customer dc ON fs.customer_id = dc.customer_id
GROUP BY dc.segment
ORDER BY revenue DESC
LIMIT 25
"""

_TOP_PRODUCTS_SQL = """
SELECT p.product_name,
       SUM(fs.total_amount) AS revenue,
       SUM(fs.profit)       AS profit
FROM fact_sales fs
JOIN dim_product p ON fs.product_id = p.product_id
GROUP BY p.product_name
ORDER BY revenue DESC
LIMIT 10
"""

_LOYALTY_SQL = """
SELECT dc.loyalty_tier,
       COUNT(DISTINCT dc.customer_id) AS customers,
       SUM(fs.total_amount)           AS revenue,
       AVG(fs.total_amount)           AS avg_order
FROM fact_sales fs
JOIN dim_customer dc ON fs.customer_id = dc.customer_id
GROUP BY dc.loyalty_tier
ORDER BY revenue DESC
LIMIT 25
"""

_QUARTERLY_SQL = """
SELECT dd.year, dd.quarter,
       SUM(fs.total_amount) AS revenue,
       SUM(fs.profit)       AS profit
FROM fact_sales fs
JOIN dim_date dd ON fs.date_id = dd.date_id
GROUP BY dd.year, dd.quarter
ORDER BY dd.year, dd.quarter
LIMIT 40
"""

_PANELS: dict[str, str] = {
    "monthly_trend": _MONTHLY_TREND_SQL,
    "by_region": _REGION_SQL,
    "by_segment": _SEGMENT_SQL,
    "top_products": _TOP_PRODUCTS_SQL,
    "by_loyalty_tier": _LOYALTY_SQL,
    "quarterly": _QUARTERLY_SQL,
}


def _records(sql: str) -> list[dict[str, Any]]:
    """Run one dashboard query and return JSON-safe records."""
    from app.api.serialization import safe_records  # local import avoids a cycle

    result = execute_query(sql.strip())
    if not result.success:
        logger.warning(f"Dashboard panel query failed: {result.error}")
        return []
    return safe_records(result.data)


def build_dashboard() -> dict[str, Any]:
    """
    Execute every dashboard panel and return a single JSON-safe payload.

    Blocking by design — the route dispatches it to a worker thread.
    """
    started = time.perf_counter()

    kpi_rows = _records(_KPI_SQL)
    kpis = kpi_rows[0] if kpi_rows else {}

    payload: dict[str, Any] = {
        "kpis": {
            "total_revenue": float(kpis.get("total_revenue") or 0.0),
            "total_profit": float(kpis.get("total_profit") or 0.0),
            "total_orders": int(kpis.get("total_orders") or 0),
            "unique_customers": int(kpis.get("unique_customers") or 0),
            "avg_order_value": round(float(kpis.get("avg_order_value") or 0.0), 2),
        },
        "panels": {name: _records(sql) for name, sql in _PANELS.items()},
    }

    payload["generated_in_ms"] = round((time.perf_counter() - started) * 1000, 2)
    logger.info(f"📊 Dashboard built in {payload['generated_in_ms']}ms")
    return payload
