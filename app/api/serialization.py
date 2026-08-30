"""
JSON serialization helpers for the API boundary.

Query results arrive as pandas DataFrames full of numpy scalars, ``Decimal``
values (PostgreSQL) and occasional ``NaN``/``inf``. None of those survive
``JSON.parse`` in a browser, so every payload is normalised here before it is
handed to FastAPI.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time as dt_time
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def to_jsonable(value: Any) -> Any:
    """Convert a single scalar into something ``json.dumps`` accepts."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        # NaN / Infinity are not valid JSON — emit null instead.
        return value if math.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def safe_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Convert a DataFrame into a JSON-safe list of row dicts."""
    if df is None or df.empty:
        return []
    return [
        {key: to_jsonable(val) for key, val in row.items()}
        for row in df.to_dict(orient="records")
    ]


def sanitize_chart_json(obj: Any) -> Any:
    """Recursively normalise a Plotly figure dict for JSON transport."""
    if isinstance(obj, dict):
        return {key: sanitize_chart_json(val) for key, val in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_chart_json(item) for item in obj]
    if isinstance(obj, np.ndarray):
        return [sanitize_chart_json(item) for item in obj.tolist()]
    return to_jsonable(obj)
