"""
Tests for SQL Confidence Scorer.
"""

import pytest
from app.llm.confidence import score_sql_confidence, build_schema_lookup


# Sample schema for testing
SAMPLE_SCHEMA = {
    "fact_sales": ["sale_id", "customer_id", "product_id", "date_id", "region_id",
                   "quantity", "unit_price", "discount", "total_amount", "cost",
                   "profit", "ship_mode", "order_number"],
    "dim_customer": ["customer_id", "first_name", "last_name", "email",
                     "segment", "loyalty_tier", "join_date", "region_id"],
    "dim_product": ["product_id", "product_name", "category", "sub_category",
                    "brand", "unit_cost", "unit_price"],
    "dim_date": ["date_id", "full_date", "day_of_month", "day_of_week",
                 "day_name", "month", "month_name", "quarter", "year", "is_weekend"],
    "dim_region": ["region_id", "region_name", "country", "state", "city", "postal_code"],
}

SAMPLE_FK_MAP = {
    "fact_sales.customer_id": "dim_customer.customer_id",
    "fact_sales.product_id": "dim_product.product_id",
    "fact_sales.date_id": "dim_date.date_id",
    "fact_sales.region_id": "dim_region.region_id",
    "dim_customer.region_id": "dim_region.region_id",
}


class TestConfidenceScorer:
    """Test the SQL confidence scoring engine."""

    def test_high_confidence_valid_query(self):
        sql = """
        SELECT dp.category, SUM(fs.total_amount) AS revenue
        FROM fact_sales fs
        JOIN dim_product dp ON fs.product_id = dp.product_id
        GROUP BY dp.category
        ORDER BY revenue DESC
        LIMIT 10
        """
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert result.score >= 70
        assert result.level in ("high", "medium")

    def test_low_confidence_nonexistent_table(self):
        sql = "SELECT * FROM nonexistent_table LIMIT 10"
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert result.score < 80
        assert len(result.warnings) > 0

    def test_penalizes_missing_limit(self):
        sql = "SELECT * FROM fact_sales"
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert result.score < 100

    def test_penalizes_dangerous_keywords(self):
        sql = "SELECT * FROM fact_sales; DROP TABLE fact_sales"
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert result.score < 70

    def test_select_check_passes(self):
        sql = "SELECT 1 LIMIT 1"
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert any(c["name"] == "is_select" and c["passed"] for c in result.checks)

    def test_non_select_penalized(self):
        sql = "DELETE FROM fact_sales"
        result = score_sql_confidence(sql, SAMPLE_SCHEMA, SAMPLE_FK_MAP)
        assert result.score < 60


class TestSchemaLookup:
    """Test the schema lookup builder."""

    def test_build_schema_lookup(self):
        tables_metadata = [
            {
                "table_name": "fact_sales",
                "columns": [{"name": "sale_id"}, {"name": "total_amount"}],
                "foreign_keys": [
                    {"column": "customer_id", "references": "dim_customer.customer_id"}
                ],
            }
        ]
        schema_tables, fk_map = build_schema_lookup(tables_metadata)
        assert "fact_sales" in schema_tables
        assert "sale_id" in schema_tables["fact_sales"]
        assert "fact_sales.customer_id" in fk_map
