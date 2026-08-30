"""
Tests for Auto-Visualization Engine.
"""

import pytest
import pandas as pd
from app.visualization.engine import determine_chart_type, ChartType


class TestChartTypeDetection:
    """Test intelligent chart type selection."""

    def test_single_value_is_kpi(self):
        df = pd.DataFrame({"total_sales": [1500000]})
        assert determine_chart_type(df) == ChartType.KPI

    def test_single_row_few_cols_is_kpi(self):
        df = pd.DataFrame({"total": [100], "avg": [50]})
        assert determine_chart_type(df) == ChartType.KPI

    def test_date_numeric_is_line(self):
        df = pd.DataFrame({
            "month_name": ["Jan", "Feb", "Mar"],
            "revenue": [1000, 1200, 1100],
        })
        assert determine_chart_type(df) == ChartType.LINE

    def test_category_numeric_is_bar(self):
        df = pd.DataFrame({
            "product": [f"Product {i}" for i in range(10)],
            "sales": [i * 100 for i in range(10)],
        })
        assert determine_chart_type(df) == ChartType.BAR

    def test_few_categories_is_pie(self):
        df = pd.DataFrame({
            "segment": ["Consumer", "Corporate", "Home Office"],
            "count": [300, 200, 100],
        })
        assert determine_chart_type(df) == ChartType.PIE

    def test_many_categories_is_hbar(self):
        df = pd.DataFrame({
            "city": [f"City {i}" for i in range(15)],
            "sales": [i * 100 for i in range(15)],
        })
        assert determine_chart_type(df) == ChartType.HORIZONTAL_BAR

    def test_two_numeric_is_scatter(self):
        df = pd.DataFrame({
            "quantity": [1, 2, 3, 4, 5],
            "revenue": [100, 200, 300, 400, 500],
        })
        assert determine_chart_type(df) == ChartType.SCATTER

    def test_empty_df_is_table(self):
        df = pd.DataFrame()
        assert determine_chart_type(df) == ChartType.TABLE

    def test_complex_multi_column_is_table(self):
        df = pd.DataFrame({
            "col1": ["a", "b"],
            "col2": ["c", "d"],
            "col3": ["e", "f"],
            "col4": ["g", "h"],
        })
        assert determine_chart_type(df) == ChartType.TABLE
