"""
SQL Confidence Scorer — rates how trustworthy a generated SQL query is.

Checks:
  1. All referenced tables exist in the schema
  2. All referenced columns exist in their respective tables
  3. JOIN keys align with actual FK relationships
  4. Aggregations have GROUP BY when needed
  5. LIMIT clause is present

Returns a score 0–100 with detailed breakdown.
"""

import re
from dataclasses import dataclass, field
from loguru import logger
import sqlparse
from sqlparse.sql import IdentifierList, Identifier, Where, Parenthesis
from sqlparse.tokens import Keyword, DML


@dataclass
class ConfidenceResult:
    """Detailed confidence assessment."""
    score: int = 100  # starts at 100, deductions applied
    level: str = "high"  # high / medium / low
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def deduct(self, points: int, reason: str):
        self.score = max(0, self.score - points)
        self.warnings.append(reason)

    def add_check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append({"name": name, "passed": passed, "detail": detail})

    def finalize(self):
        if self.score >= 75:
            self.level = "high"
        elif self.score >= 50:
            self.level = "medium"
        else:
            self.level = "low"
        return self


def score_sql_confidence(
    sql: str,
    schema_tables: dict[str, list[str]],
    fk_map: dict[str, str],
) -> ConfidenceResult:
    """
    Score the confidence of a generated SQL query.

    Args:
        sql: The generated SQL string
        schema_tables: Dict of {table_name: [column_names]}
        fk_map: Dict of {"table.column": "ref_table.ref_column"}

    Returns:
        ConfidenceResult with score, level, checks, and warnings
    """
    result = ConfidenceResult()
    sql_upper = sql.upper().strip()
    sql_lower = sql.lower().strip()

    # ── Check 1: Is it a SELECT statement? ────────────────────
    is_select = sql_upper.startswith("SELECT")
    result.add_check("is_select", is_select, "Query is a SELECT statement")
    if not is_select:
        result.deduct(50, "Query is not a SELECT statement")

    # ── Check 2: Has LIMIT clause? ────────────────────────────
    has_limit = "LIMIT" in sql_upper
    result.add_check("has_limit", has_limit, "LIMIT clause present")
    if not has_limit:
        result.deduct(10, "Missing LIMIT clause")

    # ── Check 3: No dangerous keywords ────────────────────────
    dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"]
    found_dangerous = [kw for kw in dangerous if re.search(rf'\b{kw}\b', sql_upper)]
    no_danger = len(found_dangerous) == 0
    result.add_check("no_dangerous_keywords", no_danger, f"No DDL/DML keywords")
    if not no_danger:
        result.deduct(40, f"Dangerous keywords found: {found_dangerous}")

    # ── Check 4: Referenced tables exist ──────────────────────
    referenced_tables = _extract_table_names(sql_lower)
    known_tables = set(schema_tables.keys())

    valid_tables = []
    invalid_tables = []
    for t in referenced_tables:
        if t in known_tables:
            valid_tables.append(t)
        else:
            invalid_tables.append(t)

    all_tables_valid = len(invalid_tables) == 0
    result.add_check(
        "valid_tables", all_tables_valid,
        f"Tables: {valid_tables}" + (f" | Invalid: {invalid_tables}" if invalid_tables else "")
    )
    if not all_tables_valid:
        result.deduct(20 * len(invalid_tables), f"Unknown tables: {invalid_tables}")

    # ── Check 5: Referenced columns exist ─────────────────────
    referenced_columns = _extract_column_references(sql_lower)
    invalid_columns = []
    for table, col in referenced_columns:
        if table in schema_tables:
            if col not in schema_tables[table] and col != "*":
                invalid_columns.append(f"{table}.{col}")

    all_cols_valid = len(invalid_columns) == 0
    result.add_check(
        "valid_columns", all_cols_valid,
        f"Invalid columns: {invalid_columns}" if invalid_columns else "All referenced columns valid"
    )
    if not all_cols_valid:
        result.deduct(15 * len(invalid_columns), f"Unknown columns: {invalid_columns}")

    # ── Check 6: JOINs use valid FK relationships ─────────────
    join_conditions = _extract_join_conditions(sql_lower)
    invalid_joins = []
    for left, right in join_conditions:
        # Check if this join aligns with known FKs
        if left in fk_map:
            if fk_map[left] != right:
                invalid_joins.append(f"{left} = {right}")
        elif right in fk_map:
            if fk_map[right] != left:
                invalid_joins.append(f"{left} = {right}")
        # If neither side is a known FK, that's suspicious but not fatal

    valid_joins = len(invalid_joins) == 0
    result.add_check("valid_joins", valid_joins,
                      f"Invalid joins: {invalid_joins}" if invalid_joins else "JOIN conditions valid")
    if not valid_joins:
        result.deduct(15, f"Suspicious JOINs: {invalid_joins}")

    # ── Check 7: Aggregation consistency ──────────────────────
    has_agg = any(fn in sql_upper for fn in ["SUM(", "COUNT(", "AVG(", "MIN(", "MAX("])
    has_group_by = "GROUP BY" in sql_upper
    if has_agg and not has_group_by:
        # Could be a total aggregation (no GROUP BY needed), or a mistake
        # Only deduct if there are non-aggregated columns in SELECT
        result.deduct(5, "Aggregation without GROUP BY — verify correctness")

    result.add_check("aggregation_consistent", not (has_agg and not has_group_by),
                      "Aggregation and GROUP BY are consistent")

    return result.finalize()


def _extract_table_names(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses."""
    tables = []
    # FROM table
    from_matches = re.findall(r'\bfrom\s+(\w+)', sql)
    tables.extend(from_matches)
    # JOIN table
    join_matches = re.findall(r'\bjoin\s+(\w+)', sql)
    tables.extend(join_matches)
    # Filter out aliases and SQL keywords
    sql_keywords = {"select", "where", "and", "or", "on", "as", "in", "not", "null",
                    "true", "false", "case", "when", "then", "else", "end", "between",
                    "like", "is", "order", "by", "group", "having", "limit", "offset",
                    "asc", "desc", "distinct", "inner", "outer", "left", "right", "cross",
                    "full", "natural", "using"}
    return [t for t in tables if t not in sql_keywords]


def _extract_column_references(sql: str) -> list[tuple[str, str]]:
    """Extract table.column references from SQL."""
    # Match patterns like: alias.column_name
    matches = re.findall(r'(\w+)\.(\w+)', sql)
    return matches


def _extract_join_conditions(sql: str) -> list[tuple[str, str]]:
    """Extract JOIN ON conditions as (left, right) pairs."""
    # Match: table.col = table.col
    matches = re.findall(r'(\w+\.\w+)\s*=\s*(\w+\.\w+)', sql)
    return matches


def build_schema_lookup(tables_metadata: list[dict]) -> tuple[dict, dict]:
    """
    Build lookup structures for confidence scoring.

    Returns:
        (schema_tables, fk_map) where:
        - schema_tables: {table_name: [column_names]}
        - fk_map: {"table.column": "ref_table.ref_column"}
    """
    schema_tables = {}
    fk_map = {}

    for table in tables_metadata:
        cols = [c["name"] for c in table["columns"]]
        schema_tables[table["table_name"]] = cols

        for fk in table.get("foreign_keys", []):
            key = f"{table['table_name']}.{fk['column']}"
            fk_map[key] = fk["references"]

    return schema_tables, fk_map
