"""
SQL Query Executor — safe, read-only query execution with timeout.

Executes validated SQL against the read-only database connection,
returns results as a pandas DataFrame.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import text
from loguru import logger

from app.database.connection import get_ro_engine
from app.config import settings


@dataclass
class ExecutionResult:
    """Result of SQL query execution."""
    success: bool = False
    data: pd.DataFrame | None = None
    row_count: int = 0
    columns: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    error: str | None = None

    def to_summary(self, max_rows: int = 5) -> str:
        """Convert results to a text summary for the LLM insight generator."""
        if self.data is None or self.data.empty:
            return "No data returned."

        lines = []
        lines.append(f"Total rows: {self.row_count}")
        lines.append(f"Columns: {', '.join(self.columns)}")

        # Show summary statistics for numeric columns
        numeric_cols = self.data.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            for col in numeric_cols[:3]:
                lines.append(
                    f"  {col}: min={self.data[col].min()}, "
                    f"max={self.data[col].max()}, "
                    f"avg={self.data[col].mean():.2f}"
                )

        return "\n".join(lines)

    def top_rows_str(self, n: int = 5) -> str:
        """Get top N rows as formatted string for prompts."""
        if self.data is None or self.data.empty:
            return "No data."
        return self.data.head(n).to_string(index=False)


def execute_query(sql: str) -> ExecutionResult:
    """
    Execute a validated SQL query in read-only mode.

    Features:
      - Uses the read-only database connection
      - Sets statement_timeout at session level
      - Returns pandas DataFrame for processing
      - Measures execution time
    """
    result = ExecutionResult()
    engine = get_ro_engine()

    start_time = time.time()

    try:
        with engine.connect() as conn:
            # Set statement timeout (PostgreSQL only)
            if "sqlite" not in str(engine.url):
                timeout_ms = settings.query_timeout_seconds * 1000
                conn.execute(text(f"SET statement_timeout = {timeout_ms}"))

            # Execute the query
            query_result = conn.execute(text(sql))

            # Fetch results into DataFrame
            columns = list(query_result.keys())
            rows = query_result.fetchall()

            df = pd.DataFrame(rows, columns=columns)

            result.success = True
            result.data = df
            result.row_count = len(df)
            result.columns = columns

            elapsed = (time.time() - start_time) * 1000
            result.execution_time_ms = round(elapsed, 2)

            logger.info(
                f"✅ Query executed: {result.row_count} rows, "
                f"{result.execution_time_ms}ms"
            )

    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        result.execution_time_ms = round(elapsed, 2)
        error_msg = str(e)

        # Provide user-friendly error messages
        if "statement timeout" in error_msg.lower():
            result.error = (
                f"Query timed out after {settings.query_timeout_seconds}s. "
                "Try a more specific query or add filters."
            )
        elif "permission denied" in error_msg.lower():
            result.error = "Permission denied. The database user has read-only access."
        elif "does not exist" in error_msg.lower():
            result.error = f"Database error: {error_msg}"
        else:
            result.error = f"Query execution failed: {error_msg}"

        logger.error(f"❌ Query failed ({result.execution_time_ms}ms): {result.error}")

    return result
