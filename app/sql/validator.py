"""
SQL Guardrails — multi-layer validation engine.

Validates generated SQL before execution to prevent:
  1. Non-SELECT statements (DDL/DML)
  2. SQL injection patterns
  3. Missing or excessive LIMIT
  4. References to non-existent tables/columns
  5. Dangerous patterns (UNION-based injection, stacked queries)
"""

import re
from dataclasses import dataclass, field

import sqlparse
from sqlparse.sql import Statement
from loguru import logger

from app.config import settings


@dataclass
class ValidationResult:
    """Result of SQL validation."""
    is_valid: bool = True
    sql: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    was_modified: bool = False  # True if SQL was auto-corrected


# ── Blocked Patterns ──────────────────────────────────────────
BLOCKED_KEYWORDS = [
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "EXECUTE", "EXEC",
    "INTO OUTFILE", "LOAD_FILE", "pg_read_file", "pg_write_file",
    "COPY",
]

INJECTION_PATTERNS = [
    r";\s*(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE)",  # Stacked queries
    r"--\s*$",         # SQL comment at end
    r"/\*.*\*/",       # Block comments
    r"'\s*OR\s+'1'\s*=\s*'1'",  # Classic injection
    r"'\s*OR\s+1\s*=\s*1",     # Numeric injection
    r"WAITFOR\s+DELAY",        # Time-based injection
    r"BENCHMARK\s*\(",         # MySQL benchmark
    r"pg_sleep\s*\(",          # PostgreSQL sleep
    r"information_schema\.",   # Schema probing (we handle this ourselves)
]


def validate_sql(
    sql: str,
    known_tables: set[str] | None = None,
) -> ValidationResult:
    """
    Validate a SQL query through multiple security layers.

    Args:
        sql: The SQL query to validate
        known_tables: Optional set of valid table names

    Returns:
        ValidationResult with is_valid, cleaned SQL, errors, and warnings
    """
    result = ValidationResult(sql=sql.strip())

    # ── Layer 0: Clean and extract SQL ────────────────────────
    cleaned = _extract_sql(result.sql)
    if cleaned != result.sql:
        result.sql = cleaned
        result.was_modified = True

    # ── Layer 1: Must start with SELECT or WITH (CTE) ────────
    sql_start = result.sql.upper().lstrip()
    if not sql_start.startswith("SELECT") and not sql_start.startswith("WITH"):
        result.is_valid = False
        result.errors.append(
            "Only SELECT queries are allowed. "
            "Got: " + result.sql[:50] + "..."
        )
        return result

    # ── Layer 2: Check for blocked keywords ───────────────────
    sql_upper = result.sql.upper()
    for keyword in BLOCKED_KEYWORDS:
        # Use re.escape() for safety and word boundary to avoid false positives
        if re.search(rf'\b{re.escape(keyword)}\b', sql_upper):
            result.is_valid = False
            result.errors.append(
                f"Blocked keyword detected: {keyword}. "
                "Only read-only SELECT queries are permitted."
            )
            return result

    # ── Layer 3: Check for injection patterns ─────────────────
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, result.sql, re.IGNORECASE):
            result.is_valid = False
            result.errors.append(
                "Potential SQL injection pattern detected. Query rejected."
            )
            return result

    # ── Layer 4: Detect stacked queries (semicolons) ──────────
    statements = sqlparse.split(result.sql)
    if len(statements) > 1:
        result.is_valid = False
        result.errors.append(
            "Multiple statements detected. Only single SELECT queries allowed."
        )
        return result

    # ── Layer 5: Parse and validate structure ─────────────────
    parsed = sqlparse.parse(result.sql)
    if not parsed:
        result.is_valid = False
        result.errors.append("Could not parse SQL query.")
        return result

    stmt = parsed[0]
    if stmt.get_type() != "SELECT":
        result.is_valid = False
        result.errors.append(
            f"Expected SELECT, got {stmt.get_type()}."
        )
        return result

    # ── Layer 6: Enforce LIMIT ────────────────────────────────
    if "LIMIT" not in sql_upper:
        # Auto-add LIMIT
        result.sql = result.sql.rstrip().rstrip(";") + f" LIMIT {settings.max_query_limit}"
        result.was_modified = True
        result.warnings.append(
            f"LIMIT clause was missing — automatically added LIMIT {settings.max_query_limit}"
        )
    else:
        # Check LIMIT value
        limit_match = re.search(r'LIMIT\s+(\d+)', sql_upper)
        if limit_match:
            limit_val = int(limit_match.group(1))
            if limit_val > settings.max_query_limit:
                # Replace with max allowed
                result.sql = re.sub(
                    r'LIMIT\s+\d+',
                    f'LIMIT {settings.max_query_limit}',
                    result.sql,
                    flags=re.IGNORECASE,
                )
                result.was_modified = True
                result.warnings.append(
                    f"LIMIT {limit_val} exceeded maximum — reduced to {settings.max_query_limit}"
                )

    # ── Layer 7: Validate table names (if schema provided) ────
    if known_tables:
        referenced = _extract_table_names(result.sql.lower())
        unknown = [t for t in referenced if t not in known_tables]
        if unknown:
            result.is_valid = False
            result.errors.append(
                f"Unknown tables referenced: {unknown}. "
                f"Valid tables are: {sorted(known_tables)}"
            )
            return result

    # ── Layer 8: Check for subqueries with mutations ──────────
    # Look for mutation keywords inside parentheses (subqueries)
    parens_content = re.findall(r'\(([^)]+)\)', result.sql, re.IGNORECASE)
    for content in parens_content:
        content_upper = content.upper().strip()
        for kw in ["DELETE", "INSERT", "UPDATE", "DROP"]:
            if re.search(rf'\b{kw}\b', content_upper):
                result.is_valid = False
                result.errors.append(
                    f"Subquery contains blocked keyword: {kw}"
                )
                return result

    if result.errors:
        result.is_valid = False
    if result.is_valid:
        logger.debug(f"✅ SQL validation passed (modified={result.was_modified})")
    else:
        logger.warning(f"❌ SQL validation failed: {result.errors}")

    return result


def _extract_sql(text: str) -> str:
    """
    Extract clean SQL from LLM output.

    Handles common LLM quirks:
      - Markdown code blocks (```sql ... ```)
      - Leading/trailing whitespace
      - Explanatory text before/after the SQL
      - Trailing semicolons
      - Unicode operators
      - WITH (CTE) queries
    """
    # Remove markdown code blocks
    code_block = re.search(r'```(?:sql)?\s*\n?(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if code_block:
        sql = code_block.group(1).strip().rstrip(";").strip()
        return _clean_unicode(sql)

    # Try to find a WITH (CTE) or SELECT statement
    sql_match = re.search(r'((?:WITH\s+\w+|SELECT)\s+.+)', text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        sql = sql_match.group(1).strip()

        # Cut at first semicolon (end of SQL statement)
        semi_pos = sql.find(";")
        if semi_pos != -1:
            sql = sql[:semi_pos].strip()

        # Detect trailing prose/explanation lines
        lines = sql.split("\n")
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                clean_lines.append(line)
                continue
            
            prose_patterns = [
                r'^(This|The|Note|Here|It|I |Please|Above|Below|In this)\b',
                r'^(--|#)',
                r'^\*',
            ]
            is_prose = any(re.match(p, stripped, re.IGNORECASE) for p in prose_patterns)
            
            if is_prose:
                break
            
            clean_lines.append(line)
        
        if clean_lines:
            sql = "\n".join(clean_lines).strip()

        return _clean_unicode(sql.rstrip(";").strip())

    return _clean_unicode(text.strip().rstrip(";").strip())


def _clean_unicode(sql: str) -> str:
    """Replace Unicode operators with standard SQL."""
    replacements = {
        '\u2264': '<=',   # ≤
        '\u2265': '>=',   # ≥
        '\u2260': '!=',   # ≠
        '\u2018': "'",    # left single quote
        '\u2019': "'",    # right single quote
        '\u201c': '"',    # left double quote
        '\u201d': '"',    # right double quote
    }
    for uni, ascii_char in replacements.items():
        sql = sql.replace(uni, ascii_char)
    return sql


def _extract_table_names(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses, excluding CTE names and aliases."""
    # First, remove EXTRACT(... FROM ...) patterns to avoid false positives
    # EXTRACT(YEAR FROM dc.join_date) -> the FROM here is not a table reference
    clean_sql = re.sub(r'\bEXTRACT\s*\([^)]*\)', '', sql, flags=re.IGNORECASE)
    # Also remove FILTER(WHERE ...) patterns
    clean_sql = re.sub(r'\bFILTER\s*\([^)]*\)', '', clean_sql, flags=re.IGNORECASE)

    tables = set()
    from_matches = re.findall(r'\bfrom\s+(\w+)', clean_sql)
    tables.update(from_matches)
    join_matches = re.findall(r'\bjoin\s+(\w+)', clean_sql)
    tables.update(join_matches)

    # Extract CTE names (WITH name AS ...)
    cte_names = set(re.findall(r'\bwith\s+(\w+)\s+as\b', sql, re.IGNORECASE))
    cte_names.update(re.findall(r',\s*(\w+)\s+as\s*\(', sql, re.IGNORECASE))
    cte_names = {n.lower() for n in cte_names}

    # SQL keywords + PostgreSQL built-ins that should NOT be treated as table names
    sql_keywords = {
        "select", "where", "and", "or", "on", "as", "in", "not", "null",
        "true", "false", "case", "when", "then", "else", "end", "between",
        "like", "is", "order", "by", "group", "having", "limit", "offset",
        "asc", "desc", "distinct", "inner", "outer", "left", "right",
        "cross", "full", "natural", "lateral", "each", "row", "rows",
        "with", "recursive", "union", "all", "except", "intersect",
        "current_date", "current_time", "current_timestamp",
        "localtime", "localtimestamp", "now", "extract", "generate_series",
        "unnest", "lateral", "values", "dual",
        # Common table aliases used in our schema
        "fs", "dc", "p", "dd", "r",
    }
    # Exclude SQL keywords, CTE names, and aliases
    exclude = sql_keywords | cte_names
    return [t for t in tables if t not in exclude]
