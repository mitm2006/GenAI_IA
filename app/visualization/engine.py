"""
Auto-Visualization Engine — intelligent chart selection and Plotly rendering.

Analyzes DataFrame column types and shapes to automatically choose
the most appropriate chart type, then renders it with Plotly.
"""

from enum import Enum

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from loguru import logger


class ChartType(str, Enum):
    """Supported chart types."""
    LINE = "line"
    BAR = "bar"
    HORIZONTAL_BAR = "horizontal_bar"
    PIE = "pie"
    SCATTER = "scatter"
    KPI = "kpi"
    TABLE = "table"


# ── Dark Theme Color Palette ─────────────────────────────────
COLORS = [
    "#6366f1",  # Indigo
    "#8b5cf6",  # Violet
    "#06b6d4",  # Cyan
    "#10b981",  # Emerald
    "#f59e0b",  # Amber
    "#ef4444",  # Red
    "#ec4899",  # Pink
    "#14b8a6",  # Teal
]

PLOTLY_TEMPLATE = "plotly_dark"


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert Decimal / object columns to proper numeric types.

    PostgreSQL returns Decimal for SUM, AVG, ROUND, etc.
    Pandas stores these as 'object' dtype, so is_numeric_dtype() returns False.
    This coerces them to float/int so chart detection works correctly.
    """
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass  # Genuinely non-numeric — leave as-is
    return df


def determine_chart_type(df: pd.DataFrame) -> ChartType:
    """
    Intelligently determine the best chart type for a DataFrame.

    Rules:
      - Single cell → KPI card
      - Date/time + numeric → Line chart
      - Category + numeric → Bar chart (horizontal if > 8 categories)
      - Two numeric columns → Scatter plot
      - Category + small proportions → Pie chart (if ≤ 6 categories)
      - Complex multi-column → Table
    """
    if df.empty:
        return ChartType.TABLE

    # Coerce Decimal/object columns to numeric
    df = _coerce_numeric_columns(df)

    num_rows, num_cols = df.shape

    # Single aggregate value
    if num_rows == 1 and num_cols == 1:
        return ChartType.KPI

    # Single row with few columns (aggregate summary)
    if num_rows == 1 and num_cols <= 3:
        return ChartType.KPI

    # Classify column types
    date_cols = []
    numeric_cols = []
    categorical_cols = []

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            date_cols.append(col)
        elif pd.api.types.is_numeric_dtype(df[col]):
            numeric_cols.append(col)
        else:
            # Try to identify date-like string columns
            col_lower = col.lower()
            if any(kw in col_lower for kw in ["date", "month", "year", "quarter", "week", "day"]):
                # Check if it could be ordered
                date_cols.append(col)
            else:
                categorical_cols.append(col)

    # Date + numeric → Line chart (time series)
    if date_cols and numeric_cols:
        return ChartType.LINE

    # Category + numeric
    if categorical_cols and numeric_cols:
        n_categories = df[categorical_cols[0]].nunique()
        # Small number → Pie chart
        if n_categories <= 6 and len(numeric_cols) == 1:
            return ChartType.PIE
        # Many categories → horizontal bar
        if n_categories > 8:
            return ChartType.HORIZONTAL_BAR
        return ChartType.BAR

    # Two numeric columns → Scatter
    if len(numeric_cols) >= 2 and not categorical_cols:
        return ChartType.SCATTER

    # Fallback → Table
    return ChartType.TABLE


def render_chart(
    df: pd.DataFrame,
    chart_type: ChartType | None = None,
    title: str = "",
) -> go.Figure | dict | None:
    """
    Render a Plotly chart based on the DataFrame.

    Args:
        df: Query result DataFrame
        chart_type: Override auto-detection
        title: Chart title (derived from the question)

    Returns:
        Plotly Figure object, or KPI dict, or None
    """
    if df.empty:
        return None

    # Coerce Decimal/object columns to numeric
    df = _coerce_numeric_columns(df)

    if chart_type is None:
        chart_type = determine_chart_type(df)

    logger.info(f"📊 Rendering chart: {chart_type.value} ({df.shape[0]} rows)")

    if chart_type == ChartType.KPI:
        return _render_kpi(df, title)
    elif chart_type == ChartType.LINE:
        return _render_line(df, title)
    elif chart_type == ChartType.BAR:
        return _render_bar(df, title)
    elif chart_type == ChartType.HORIZONTAL_BAR:
        return _render_hbar(df, title)
    elif chart_type == ChartType.PIE:
        return _render_pie(df, title)
    elif chart_type == ChartType.SCATTER:
        return _render_scatter(df, title)
    elif chart_type == ChartType.TABLE:
        return _render_table(df, title)

    return None


def _apply_theme(fig: go.Figure, title: str) -> go.Figure:
    """Apply consistent dark theme to all charts."""
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=dict(
            text=title,
            font=dict(size=18, color="#e2e8f0"),
            x=0.5,
        ),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#1e293b",
        font=dict(color="#cbd5e1", family="Inter, sans-serif"),
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(
            bgcolor="rgba(30,41,59,0.8)",
            bordercolor="#334155",
            borderwidth=1,
        ),
    )
    fig.update_xaxes(gridcolor="#334155", zeroline=False)
    fig.update_yaxes(gridcolor="#334155", zeroline=False)
    return fig


def _render_kpi(df: pd.DataFrame, title: str) -> dict:
    """Render a KPI metric card."""
    values = {}
    for col in df.columns:
        val = df[col].iloc[0]
        if isinstance(val, (int, float)):
            if abs(val) >= 1_000_000:
                formatted = f"₹{val/1_000_000:.2f}M"
            elif abs(val) >= 1_000:
                formatted = f"₹{val/1_000:.1f}K"
            else:
                formatted = f"{val:,.2f}"
        else:
            formatted = str(val)
        values[col] = formatted

    return {
        "type": "kpi",
        "title": title,
        "values": values,
    }


def _render_line(df: pd.DataFrame, title: str) -> go.Figure:
    """Render a line chart for time series data."""
    # Identify x (date/time) and y (numeric) columns
    x_col = None
    y_cols = []

    for col in df.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in ["date", "month", "year", "quarter", "week", "day"]):
            if x_col is None:
                x_col = col
        elif pd.api.types.is_numeric_dtype(df[col]):
            y_cols.append(col)

    if not x_col:
        x_col = df.columns[0]
    if not y_cols:
        y_cols = [c for c in df.columns if c != x_col and pd.api.types.is_numeric_dtype(df[c])]

    fig = go.Figure()
    for i, y_col in enumerate(y_cols):
        fig.add_trace(go.Scatter(
            x=df[x_col],
            y=df[y_col],
            mode="lines+markers",
            name=y_col.replace("_", " ").title(),
            line=dict(color=COLORS[i % len(COLORS)], width=2.5),
            marker=dict(size=6),
        ))

    return _apply_theme(fig, title)


def _render_bar(df: pd.DataFrame, title: str) -> go.Figure:
    """Render a vertical bar chart."""
    cat_col = None
    val_cols = []

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            val_cols.append(col)
        elif cat_col is None:
            cat_col = col

    if not cat_col:
        cat_col = df.columns[0]
    if not val_cols:
        val_cols = [c for c in df.columns if c != cat_col]

    fig = go.Figure()
    for i, val_col in enumerate(val_cols):
        fig.add_trace(go.Bar(
            x=df[cat_col],
            y=df[val_col],
            name=val_col.replace("_", " ").title(),
            marker_color=COLORS[i % len(COLORS)],
        ))

    return _apply_theme(fig, title)


def _render_hbar(df: pd.DataFrame, title: str) -> go.Figure:
    """Render a horizontal bar chart (for many categories)."""
    cat_col = None
    val_col = None

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and val_col is None:
            val_col = col
        elif cat_col is None:
            cat_col = col

    if not cat_col:
        cat_col = df.columns[0]
    if not val_col:
        val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    fig = go.Figure(go.Bar(
        y=df[cat_col],
        x=df[val_col],
        orientation="h",
        marker_color=COLORS[0],
    ))

    return _apply_theme(fig, title)


def _render_pie(df: pd.DataFrame, title: str) -> go.Figure:
    """Render a donut/pie chart."""
    cat_col = None
    val_col = None

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) and val_col is None:
            val_col = col
        elif cat_col is None:
            cat_col = col

    fig = go.Figure(go.Pie(
        labels=df[cat_col],
        values=df[val_col],
        hole=0.4,
        marker=dict(colors=COLORS[:len(df)]),
        textinfo="label+percent",
        textfont=dict(size=12),
    ))

    return _apply_theme(fig, title)


def _render_scatter(df: pd.DataFrame, title: str) -> go.Figure:
    """Render a scatter plot."""
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    x_col = numeric_cols[0] if len(numeric_cols) > 0 else df.columns[0]
    y_col = numeric_cols[1] if len(numeric_cols) > 1 else df.columns[1]

    fig = px.scatter(
        df, x=x_col, y=y_col,
        color_discrete_sequence=COLORS,
    )

    return _apply_theme(fig, title)


def _render_table(df: pd.DataFrame, title: str) -> go.Figure:
    """Render an interactive data table."""
    fig = go.Figure(go.Table(
        header=dict(
            values=[f"<b>{c.replace('_', ' ').title()}</b>" for c in df.columns],
            fill_color="#1e293b",
            font=dict(color="#e2e8f0", size=13),
            align="left",
            line_color="#334155",
        ),
        cells=dict(
            values=[df[col].tolist() for col in df.columns],
            fill_color="#0f172a",
            font=dict(color="#cbd5e1", size=12),
            align="left",
            line_color="#334155",
        ),
    ))

    return _apply_theme(fig, title)
