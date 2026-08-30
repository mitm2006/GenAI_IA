"""
Performance Metrics Tracker — records per-query statistics.

Tracks latency, token count, success/failure rates, confidence scores,
and provides aggregate metrics for the dashboard.
"""

import time
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime, timedelta
from threading import Lock


@dataclass
class QueryMetric:
    """Metrics for a single query."""
    question: str
    sql: str
    success: bool
    execution_time_ms: float
    confidence_score: int
    row_count: int
    retry_count: int
    timestamp: datetime = field(default_factory=datetime.now)
    error: str | None = None


class MetricsTracker:
    """
    Thread-safe metrics tracker with a rolling window.

    Keeps the last 1000 queries and provides aggregate statistics.
    """

    def __init__(self, max_entries: int = 1000):
        self.max_entries = max_entries
        self._metrics: deque[QueryMetric] = deque(maxlen=max_entries)
        self._lock = Lock()

    def record(
        self,
        question: str,
        sql: str,
        success: bool,
        execution_time_ms: float,
        confidence_score: int = 0,
        row_count: int = 0,
        retry_count: int = 0,
        error: str | None = None,
    ) -> None:
        """Record a query metric."""
        metric = QueryMetric(
            question=question,
            sql=sql,
            success=success,
            execution_time_ms=execution_time_ms,
            confidence_score=confidence_score,
            row_count=row_count,
            retry_count=retry_count,
            error=error,
        )
        with self._lock:
            self._metrics.append(metric)

    def get_aggregate_stats(self) -> dict:
        """Get aggregate statistics."""
        with self._lock:
            if not self._metrics:
                return {
                    "total_queries": 0,
                    "success_rate": 0.0,
                    "avg_latency_ms": 0.0,
                    "avg_confidence": 0.0,
                    "queries_today": 0,
                    "total_retries": 0,
                }

            all_metrics = list(self._metrics)

        total = len(all_metrics)
        successful = sum(1 for m in all_metrics if m.success)
        avg_latency = sum(m.execution_time_ms for m in all_metrics) / total
        avg_confidence = (
            sum(m.confidence_score for m in all_metrics) / total
            if total > 0 else 0
        )

        # Today's count
        today = datetime.now().date()
        queries_today = sum(
            1 for m in all_metrics
            if m.timestamp.date() == today
        )

        total_retries = sum(m.retry_count for m in all_metrics)

        return {
            "total_queries": total,
            "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
            "avg_latency_ms": round(avg_latency, 1),
            "avg_confidence": round(avg_confidence, 1),
            "queries_today": queries_today,
            "total_retries": total_retries,
        }

    def get_recent_queries(self, n: int = 10) -> list[dict]:
        """Get the most recent N queries."""
        with self._lock:
            recent = list(self._metrics)[-n:]

        return [
            {
                "question": m.question,
                "success": m.success,
                "execution_time_ms": m.execution_time_ms,
                "confidence_score": m.confidence_score,
                "row_count": m.row_count,
                "timestamp": m.timestamp.isoformat(),
                "error": m.error,
            }
            for m in reversed(recent)
        ]


# Singleton
metrics_tracker = MetricsTracker()
