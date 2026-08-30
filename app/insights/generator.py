"""
Insight Generator — produces fast business-level summaries from query results.

Uses code-based analysis instead of LLM to generate instant insights.
This eliminates the second LLM call that was doubling query time.
"""

import pandas as pd
from loguru import logger

from app.sql.executor import ExecutionResult


def generate_insight(
    question: str,
    exec_result: ExecutionResult,
) -> str:
    """
    Generate a business insight from query results (NO LLM call - instant).
    """
    if not exec_result.success or exec_result.data is None or exec_result.data.empty:
        return "No data was returned for this query."

    try:
        df = exec_result.data
        row_count = exec_result.row_count
        columns = exec_result.columns

        # Coerce Decimal to float for analysis
        for col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]):
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    pass

        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        categorical_cols = [c for c in df.columns if c not in numeric_cols]

        parts = []

        # Single-row KPI result
        if row_count == 1:
            items = []
            for col in df.columns:
                val = df[col].iloc[0]
                label = col.replace("_", " ").title()
                if isinstance(val, (int, float)):
                    if abs(val) >= 1_000_000:
                        items.append(f"**{label}**: ${val/1_000_000:.2f}M")
                    elif abs(val) >= 1_000:
                        items.append(f"**{label}**: ${val/1_000:.1f}K")
                    else:
                        items.append(f"**{label}**: {val:,.2f}")
                else:
                    items.append(f"**{label}**: {val}")
            parts.append(f"Result: {', '.join(items)}.")
            return " ".join(parts)

        # Multi-row results
        if categorical_cols and numeric_cols:
            cat_col = categorical_cols[0]
            val_col = numeric_cols[0]
            val_label = val_col.replace("_", " ").title()

            # Top performer
            top_idx = df[val_col].idxmax()
            top_name = df[cat_col].iloc[top_idx]
            top_val = df[val_col].iloc[top_idx]

            if top_val >= 1_000_000:
                top_formatted = f"${top_val/1_000_000:.2f}M"
            elif top_val >= 1_000:
                top_formatted = f"${top_val/1_000:.1f}K"
            else:
                top_formatted = f"{top_val:,.2f}"

            parts.append(
                f"**{top_name}** leads with {val_label} of {top_formatted}."
            )

            # Compare top vs bottom if multiple rows
            if row_count >= 3:
                bottom_idx = df[val_col].idxmin()
                bottom_name = df[cat_col].iloc[bottom_idx]
                bottom_val = df[val_col].iloc[bottom_idx]
                if bottom_val > 0:
                    ratio = top_val / bottom_val
                    parts.append(
                        f"The top performer is {ratio:.1f}x higher than "
                        f"**{bottom_name}** (lowest)."
                    )

            # Total and average
            total = df[val_col].sum()
            avg = df[val_col].mean()
            if total >= 1_000_000:
                parts.append(
                    f"Total across all {row_count} entries: "
                    f"${total/1_000_000:.2f}M (avg: ${avg/1_000_000:.2f}M)."
                )
            elif total >= 1_000:
                parts.append(
                    f"Total across all {row_count} entries: "
                    f"${total/1_000:.1f}K (avg: ${avg/1_000:.1f}K)."
                )

        elif numeric_cols:
            # Numeric-only data (trends)
            for col in numeric_cols[:2]:
                label = col.replace("_", " ").title()
                total = df[col].sum()
                avg = df[col].mean()
                if total >= 1_000_000:
                    parts.append(f"**{label}** total: ${total/1_000_000:.2f}M, avg: ${avg/1_000_000:.2f}M.")
                else:
                    parts.append(f"**{label}** total: {total:,.2f}, avg: {avg:,.2f}.")

        if not parts:
            parts.append(f"Query returned {row_count} rows across {len(columns)} columns.")

        insight = " ".join(parts)
        logger.info(f"💡 Insight generated ({len(insight)} chars)")
        return insight

    except Exception as e:
        logger.error(f"Insight generation failed: {e}")
        return f"Query returned {exec_result.row_count} rows."
