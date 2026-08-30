"""
Schema metadata extractor — reads database structure at runtime.

Works with both PostgreSQL and SQLite using SQLAlchemy's inspect API.

Produces structured metadata per table including:
  - Column names, types, nullable flags
  - Primary keys, foreign key relationships
  - Sample values (for embedding context)
  - Human-readable descriptions
"""

from typing import Any
from sqlalchemy import text, inspect as sa_inspect
from loguru import logger

from app.database.connection import get_rw_engine


def extract_schema_metadata() -> list[dict[str, Any]]:
    """
    Extract full schema metadata using SQLAlchemy's database-agnostic inspect API.

    Returns a list of dicts, one per table:
    {
        "table_name": "fact_sales",
        "columns": [
            {"name": "sale_id", "type": "INTEGER", "nullable": False, "is_pk": True},
            ...
        ],
        "foreign_keys": [
            {"column": "customer_id", "references": "dim_customer.customer_id"},
            ...
        ],
        "row_count": 55000,
        "description": "Human-readable table summary for embedding"
    }
    """
    engine = get_rw_engine()
    inspector = sa_inspect(engine)
    tables = []

    # Get all table names
    table_names = sorted(inspector.get_table_names())

    with engine.connect() as conn:
        for table_name in table_names:
            table_meta = {
                "table_name": table_name,
                "columns": [],
                "foreign_keys": [],
                "primary_keys": [],
                "row_count": 0,
                "description": "",
            }

            # ── Columns (via inspector) ───────────────────────
            columns = inspector.get_columns(table_name)
            pk_info = inspector.get_pk_constraint(table_name)
            pk_columns = pk_info.get("constrained_columns", []) if pk_info else []

            for col in columns:
                col_type = str(col["type"])
                is_pk = col["name"] in pk_columns
                table_meta["columns"].append({
                    "name": col["name"],
                    "type": col_type,
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default", "")) if col.get("default") else None,
                    "is_pk": is_pk,
                })
                if is_pk:
                    table_meta["primary_keys"].append(col["name"])

            # ── Foreign Keys (via inspector) ──────────────────
            fks = inspector.get_foreign_keys(table_name)
            for fk in fks:
                ref_table = fk["referred_table"]
                for local_col, ref_col in zip(
                    fk["constrained_columns"], fk["referred_columns"]
                ):
                    table_meta["foreign_keys"].append({
                        "column": local_col,
                        "references": f"{ref_table}.{ref_col}",
                    })

            # ── Row Count ─────────────────────────────────────
            try:
                cnt = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                table_meta["row_count"] = cnt.scalar()
            except Exception:
                table_meta["row_count"] = 0

            # ── Sample Values (top 5 distinct per non-PK column) ──
            for col in table_meta["columns"]:
                if col["is_pk"]:
                    continue
                try:
                    samples = conn.execute(text(
                        f"SELECT DISTINCT \"{col['name']}\" FROM {table_name} "
                        f"WHERE \"{col['name']}\" IS NOT NULL LIMIT 5"
                    ))
                    col["sample_values"] = [str(s[0]) for s in samples]
                except Exception:
                    col["sample_values"] = []

            # ── Build Description ─────────────────────────────
            table_meta["description"] = _build_description(table_meta)
            tables.append(table_meta)

    logger.info(f"📋 Extracted metadata for {len(tables)} tables")
    return tables


def _build_description(meta: dict) -> str:
    """Build a natural-language description of a table for embedding."""
    lines = [f"Table: {meta['table_name']} ({meta['row_count']} rows)"]

    col_descs = []
    for col in meta["columns"]:
        desc = f"  - {col['name']} ({col['type']})"
        if col.get("is_pk"):
            desc += " [PRIMARY KEY]"
        if col.get("sample_values"):
            desc += f" examples: {', '.join(col['sample_values'][:3])}"
        col_descs.append(desc)
    lines.append("Columns:\n" + "\n".join(col_descs))

    if meta["foreign_keys"]:
        fk_descs = [
            f"  - {fk['column']} → {fk['references']}"
            for fk in meta["foreign_keys"]
        ]
        lines.append("Foreign Keys:\n" + "\n".join(fk_descs))

    return "\n".join(lines)


def get_schema_for_prompt(tables_metadata: list[dict]) -> str:
    """
    Format schema metadata into a compact string for the LLM prompt.

    This is the version injected directly into the prompt — concise but complete.
    """
    sections = []
    for t in tables_metadata:
        cols = ", ".join(
            f"{c['name']} ({c['type']}{'  PK' if c.get('is_pk') else ''})"
            for c in t["columns"]
        )
        fks = ""
        if t["foreign_keys"]:
            fk_strs = [f"{fk['column']} → {fk['references']}" for fk in t["foreign_keys"]]
            fks = f"\n  Foreign Keys: {'; '.join(fk_strs)}"
        sections.append(f"TABLE {t['table_name']}: {cols}{fks}")

    return "\n\n".join(sections)
