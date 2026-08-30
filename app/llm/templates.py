"""
SQL Query Template Library — pre-validated SQL patterns for common questions.

Stores question→SQL pairs indexed by semantic similarity. When a user asks
a question, the closest matching template is injected into the prompt so
the LLM has a concrete working example to follow.
"""

import os
from loguru import logger

import chromadb
from sentence_transformers import SentenceTransformer

from app.config import settings

# ── Pre-validated SQL templates ────────────────────────────────
# Each entry: (natural language question, working PostgreSQL SQL)

QUERY_TEMPLATES = [
    # ── Basic aggregation ──────────────────────────────────────
    (
        "What were total sales in 2024?",
        "SELECT SUM(fs.total_amount) AS total_sales FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2024 LIMIT 1"
    ),
    (
        "What is the total revenue?",
        "SELECT SUM(fs.total_amount) AS total_revenue FROM fact_sales fs LIMIT 1"
    ),
    (
        "What is the total profit?",
        "SELECT SUM(fs.profit) AS total_profit FROM fact_sales fs LIMIT 1"
    ),
    (
        "What is the average order value?",
        "SELECT ROUND(AVG(fs.total_amount), 2) AS avg_order_value FROM fact_sales fs LIMIT 1"
    ),
    (
        "How many orders were placed?",
        "SELECT COUNT(*) AS total_orders FROM fact_sales fs LIMIT 1"
    ),
    (
        "How many customers do we have?",
        "SELECT COUNT(DISTINCT customer_id) AS total_customers FROM dim_customer LIMIT 1"
    ),

    # ── Top N queries ──────────────────────────────────────────
    (
        "Top 10 products by revenue",
        "SELECT p.product_name, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.product_name ORDER BY revenue DESC LIMIT 10"
    ),
    (
        "Top 5 cities by total profit",
        "SELECT r.city, SUM(fs.profit) AS total_profit FROM fact_sales fs JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.city ORDER BY total_profit DESC LIMIT 5"
    ),
    (
        "Top 5 customers by total spending",
        "SELECT dc.first_name, dc.last_name, SUM(fs.total_amount) AS total_spent FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY dc.customer_id, dc.first_name, dc.last_name ORDER BY total_spent DESC LIMIT 5"
    ),
    (
        "Top product categories by revenue",
        "SELECT p.category, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.category ORDER BY revenue DESC LIMIT 10"
    ),
    (
        "Which regions have the highest sales?",
        "SELECT r.region_name, SUM(fs.total_amount) AS total_sales FROM fact_sales fs JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.region_name ORDER BY total_sales DESC LIMIT 10"
    ),
    (
        "Best-selling products in each city",
        "SELECT r.city, p.product_name, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.city, p.product_name ORDER BY r.city, revenue DESC LIMIT 20"
    ),
    (
        "Most profitable cities and their best-selling products",
        "SELECT r.city, p.product_name, SUM(fs.profit) AS total_profit FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.city, p.product_name ORDER BY total_profit DESC LIMIT 20"
    ),

    # ── Time-based queries ─────────────────────────────────────
    (
        "Monthly sales trend for 2024",
        "SELECT dd.month, dd.month_name, SUM(fs.total_amount) AS monthly_sales FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2024 GROUP BY dd.month, dd.month_name ORDER BY dd.month LIMIT 12"
    ),
    (
        "Quarterly revenue comparison",
        "SELECT dd.year, dd.quarter, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year IN (2024, 2025) GROUP BY dd.year, dd.quarter ORDER BY dd.year, dd.quarter LIMIT 8"
    ),
    (
        "Sales last quarter",
        "SELECT SUM(fs.total_amount) AS total_sales FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2025 AND dd.quarter = 4 LIMIT 1"
    ),
    (
        "Daily sales trend this month",
        "SELECT dd.full_date, SUM(fs.total_amount) AS daily_sales FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2025 AND dd.month = 12 GROUP BY dd.full_date ORDER BY dd.full_date LIMIT 31"
    ),
    (
        "Weekend vs weekday sales comparison",
        "SELECT CASE WHEN dd.is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type, COUNT(*) AS order_count, SUM(fs.total_amount) AS total_sales, ROUND(AVG(fs.total_amount), 2) AS avg_sale FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id GROUP BY dd.is_weekend LIMIT 2"
    ),

    # ── Segment & loyalty ──────────────────────────────────────
    (
        "Sales by customer segment",
        "SELECT dc.segment, SUM(fs.total_amount) AS revenue, COUNT(*) AS orders FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY dc.segment ORDER BY revenue DESC LIMIT 10"
    ),
    (
        "Revenue by customer loyalty tier",
        "SELECT dc.loyalty_tier, SUM(fs.total_amount) AS revenue, COUNT(DISTINCT dc.customer_id) AS customers FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY dc.loyalty_tier ORDER BY revenue DESC LIMIT 10"
    ),
    (
        "Customer count by loyalty tier in each region",
        "SELECT r.region_name, dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS customer_count FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.region_name, dc.loyalty_tier ORDER BY r.region_name, customer_count DESC LIMIT 30"
    ),
    (
        "How many customers from each loyalty tier made a purchase last month?",
        "SELECT dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS customer_count, ROUND(AVG(fs.total_amount), 2) AS avg_order_value FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2025 AND dd.month = 11 GROUP BY dc.loyalty_tier ORDER BY customer_count DESC LIMIT 10"
    ),
    (
        "Top 5 regions with highest customer loyalty",
        "SELECT r.region_name, dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS customer_count, SUM(fs.total_amount) AS total_revenue FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.region_name, dc.loyalty_tier ORDER BY total_revenue DESC LIMIT 20"
    ),

    # ── Year-over-year comparisons ─────────────────────────────
    (
        "Year-over-year sales growth by region",
        "SELECT r.region_name, SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END) AS sales_2024, SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) AS sales_2025, ROUND((SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) - SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END)) * 100.0 / NULLIF(SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END), 0), 2) AS growth_pct FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_region r ON fs.region_id = r.region_id WHERE dd.year IN (2024, 2025) GROUP BY r.region_name ORDER BY growth_pct DESC LIMIT 10"
    ),
    (
        "Compare this year vs last year revenue by segment",
        "SELECT dc.segment, SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END) AS revenue_2024, SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) AS revenue_2025, ROUND((SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) - SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END)) * 100.0 / NULLIF(SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END), 0), 2) AS growth_pct FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_customer dc ON fs.customer_id = dc.customer_id WHERE dd.year IN (2024, 2025) GROUP BY dc.segment ORDER BY growth_pct DESC LIMIT 10"
    ),
    (
        "Which regions showed the highest growth in sales over the past year compared to the previous year?",
        "SELECT r.region_name, SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END) AS sales_2024, SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) AS sales_2025, ROUND((SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) - SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END)) * 100.0 / NULLIF(SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END), 0), 2) AS growth_pct FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_region r ON fs.region_id = r.region_id WHERE dd.year IN (2024, 2025) GROUP BY r.region_name ORDER BY growth_pct DESC LIMIT 10"
    ),
    (
        "How has customer loyalty evolved over time by region or loyalty tier?",
        "SELECT dd.year, r.region_name, dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS customer_count, SUM(fs.total_amount) AS total_revenue FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY dd.year, r.region_name, dc.loyalty_tier ORDER BY dd.year, r.region_name, customer_count DESC LIMIT 50"
    ),

    # ── Product analysis ───────────────────────────────────────
    (
        "Revenue by product category and sub-category",
        "SELECT p.category, p.sub_category, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.category, p.sub_category ORDER BY p.category, revenue DESC LIMIT 30"
    ),
    (
        "Most profitable product categories",
        "SELECT p.category, SUM(fs.profit) AS total_profit, ROUND(AVG(fs.profit), 2) AS avg_profit FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.category ORDER BY total_profit DESC LIMIT 10"
    ),
    (
        "Products with the highest discount",
        "SELECT p.product_name, ROUND(AVG(fs.discount), 2) AS avg_discount, SUM(fs.total_amount) AS total_revenue FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.product_name ORDER BY avg_discount DESC LIMIT 10"
    ),
    (
        "Which brands have highest profit margins?",
        "SELECT p.brand, SUM(fs.profit) AS total_profit, SUM(fs.total_amount) AS total_revenue, ROUND(SUM(fs.profit) * 100.0 / NULLIF(SUM(fs.total_amount), 0), 2) AS profit_margin_pct FROM fact_sales fs JOIN dim_product p ON fs.product_id = p.product_id GROUP BY p.brand ORDER BY profit_margin_pct DESC LIMIT 10"
    ),

    # ── Regional analysis ──────────────────────────────────────
    (
        "Sales by state",
        "SELECT r.state, SUM(fs.total_amount) AS total_sales FROM fact_sales fs JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.state ORDER BY total_sales DESC LIMIT 20"
    ),
    (
        "Profit by region and city",
        "SELECT r.region_name, r.city, SUM(fs.profit) AS total_profit FROM fact_sales fs JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.region_name, r.city ORDER BY total_profit DESC LIMIT 20"
    ),

    # ── Shipping analysis ──────────────────────────────────────
    (
        "Sales by shipping mode",
        "SELECT fs.ship_mode, COUNT(*) AS order_count, SUM(fs.total_amount) AS revenue FROM fact_sales fs GROUP BY fs.ship_mode ORDER BY revenue DESC LIMIT 10"
    ),

    # ── Conditional counting ───────────────────────────────────
    (
        "Count of premium customers by region",
        "SELECT r.region_name, COUNT(DISTINCT dc.customer_id) AS premium_customers FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_region r ON fs.region_id = r.region_id WHERE dc.loyalty_tier = 'Premium' GROUP BY r.region_name ORDER BY premium_customers DESC LIMIT 10"
    ),
    (
        "Revenue from each customer segment in each year",
        "SELECT dd.year, dc.segment, SUM(fs.total_amount) AS revenue FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY dd.year, dc.segment ORDER BY dd.year, revenue DESC LIMIT 30"
    ),

    # ── Complex analytical queries ────────────────────────────────
    (
        "Which products are most frequently purchased together or cross-selling opportunities",
        "SELECT p1.product_name AS product_a, p2.product_name AS product_b, COUNT(*) AS times_bought_together FROM fact_sales fs1 JOIN fact_sales fs2 ON fs1.order_number = fs2.order_number AND fs1.product_id < fs2.product_id JOIN dim_product p1 ON fs1.product_id = p1.product_id JOIN dim_product p2 ON fs2.product_id = p2.product_id GROUP BY p1.product_name, p2.product_name ORDER BY times_bought_together DESC LIMIT 20"
    ),
    (
        "Compare loyal vs non-loyal customer spending by region",
        "SELECT r.region_name, COUNT(DISTINCT CASE WHEN dc.loyalty_tier IN ('Gold','Platinum') THEN dc.customer_id END) AS loyal_customers, COUNT(DISTINCT CASE WHEN dc.loyalty_tier IN ('Bronze','Silver') THEN dc.customer_id END) AS other_customers, ROUND(SUM(CASE WHEN dc.loyalty_tier IN ('Gold','Platinum') THEN fs.total_amount ELSE 0 END), 2) AS loyal_spending, ROUND(SUM(CASE WHEN dc.loyalty_tier IN ('Bronze','Silver') THEN fs.total_amount ELSE 0 END), 2) AS other_spending FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_region r ON fs.region_id = r.region_id GROUP BY r.region_name ORDER BY loyal_spending DESC LIMIT 20"
    ),
    (
        "Customer retention rate by loyalty tier",
        "SELECT dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS total_customers, COUNT(DISTINCT CASE WHEN dd.year = 2025 THEN dc.customer_id END) AS active_2025, COUNT(DISTINCT CASE WHEN dd.year = 2024 THEN dc.customer_id END) AS active_2024, ROUND(COUNT(DISTINCT CASE WHEN dd.year = 2025 THEN dc.customer_id END) * 100.0 / NULLIF(COUNT(DISTINCT CASE WHEN dd.year = 2024 THEN dc.customer_id END), 0), 2) AS retention_pct FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year IN (2024, 2025) GROUP BY dc.loyalty_tier ORDER BY retention_pct DESC LIMIT 10"
    ),
    (
        "Average lifetime value by customer loyalty tier",
        "SELECT dc.loyalty_tier, COUNT(DISTINCT dc.customer_id) AS num_customers, ROUND(SUM(fs.total_amount) / NULLIF(COUNT(DISTINCT dc.customer_id), 0), 2) AS avg_lifetime_value, ROUND(SUM(fs.profit) / NULLIF(COUNT(DISTINCT dc.customer_id), 0), 2) AS avg_lifetime_profit FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY dc.loyalty_tier ORDER BY avg_lifetime_value DESC LIMIT 10"
    ),
    (
        "New customer acquisition by month",
        "SELECT dd.year, dd.month, dd.month_name, COUNT(DISTINCT dc.customer_id) AS new_customers FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dc.join_date >= '2025-01-01' GROUP BY dd.year, dd.month, dd.month_name ORDER BY dd.year, dd.month LIMIT 12"
    ),
    (
        "Year-over-year revenue growth by region",
        "SELECT r.region_name, ROUND(SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END), 2) AS revenue_2024, ROUND(SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END), 2) AS revenue_2025, ROUND((SUM(CASE WHEN dd.year = 2025 THEN fs.total_amount ELSE 0 END) - SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END)) * 100.0 / NULLIF(SUM(CASE WHEN dd.year = 2024 THEN fs.total_amount ELSE 0 END), 0), 2) AS growth_pct FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id JOIN dim_region r ON fs.region_id = r.region_id WHERE dd.year IN (2024, 2025) GROUP BY r.region_name ORDER BY growth_pct DESC LIMIT 10"
    ),
    (
        "Impact of discounts on revenue and profit",
        "SELECT CASE WHEN fs.discount = 0 THEN 'No Discount' WHEN fs.discount < 0.1 THEN 'Low (0-10%)' WHEN fs.discount < 0.2 THEN 'Medium (10-20%)' ELSE 'High (20%+)' END AS discount_band, COUNT(*) AS order_count, ROUND(SUM(fs.total_amount), 2) AS total_revenue, ROUND(SUM(fs.profit), 2) AS total_profit, ROUND(AVG(fs.profit), 2) AS avg_profit FROM fact_sales fs GROUP BY discount_band ORDER BY total_revenue DESC LIMIT 10"
    ),
    (
        "Weekend vs weekday sales comparison",
        "SELECT CASE WHEN dd.is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_type, COUNT(*) AS order_count, ROUND(SUM(fs.total_amount), 2) AS total_revenue, ROUND(AVG(fs.total_amount), 2) AS avg_order_value FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id GROUP BY day_type LIMIT 2"
    ),
    (
        "Customer spending analysis by membership length",
        "SELECT CASE WHEN dc.join_date >= '2025-01-01' THEN 'New (2025)' WHEN dc.join_date >= '2024-01-01' THEN '1 Year' WHEN dc.join_date >= '2023-01-01' THEN '2 Years' ELSE '3+ Years' END AS membership_length, COUNT(DISTINCT dc.customer_id) AS customers, ROUND(SUM(fs.total_amount) / NULLIF(COUNT(DISTINCT dc.customer_id), 0), 2) AS avg_spend_per_customer FROM fact_sales fs JOIN dim_customer dc ON fs.customer_id = dc.customer_id GROUP BY membership_length ORDER BY avg_spend_per_customer DESC LIMIT 10"
    ),
    (
        "Monthly revenue and profit trend",
        "SELECT dd.year, dd.month, dd.month_name, ROUND(SUM(fs.total_amount), 2) AS revenue, ROUND(SUM(fs.profit), 2) AS profit, ROUND(SUM(fs.profit) * 100.0 / NULLIF(SUM(fs.total_amount), 0), 2) AS profit_margin_pct FROM fact_sales fs JOIN dim_date dd ON fs.date_id = dd.date_id WHERE dd.year = 2025 GROUP BY dd.year, dd.month, dd.month_name ORDER BY dd.month LIMIT 12"
    ),
]


# ── ChromaDB Template Store ────────────────────────────────────

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "chroma_data")

_template_collection = None
_model = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the embedding model (shared with schema embeddings)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def _get_template_collection():
    """Get or create the query template collection in ChromaDB."""
    global _template_collection
    if _template_collection is None:
        client = chromadb.PersistentClient(path=os.path.abspath(CHROMA_DIR))
        _template_collection = client.get_or_create_collection(
            name="query_templates",
            metadata={"hnsw:space": "cosine"},
        )
    return _template_collection


def initialize_templates() -> None:
    """Embed all query templates into ChromaDB. Called once at startup."""
    model = _get_model()
    collection = _get_template_collection()

    # Clear and re-embed
    existing = collection.count()
    if existing > 0:
        all_ids = collection.get()["ids"]
        if all_ids:
            collection.delete(ids=all_ids)

    questions = [q for q, _ in QUERY_TEMPLATES]
    sqls = [s for _, s in QUERY_TEMPLATES]

    embeddings = model.encode(questions).tolist()

    collection.add(
        documents=questions,
        embeddings=embeddings,
        ids=[f"template_{i}" for i in range(len(QUERY_TEMPLATES))],
        metadatas=[{"sql": sql, "question": q} for q, sql in QUERY_TEMPLATES],
    )

    logger.info(f"✅ Indexed {len(QUERY_TEMPLATES)} SQL query templates")


def find_similar_templates(query: str, top_k: int = 1) -> list[dict]:
    """
    Find the most similar query templates for a user question.

    Returns list of {"question": str, "sql": str, "distance": float}
    """
    model = _get_model()
    collection = _get_template_collection()

    if collection.count() == 0:
        return []

    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
    )

    templates = []
    if results["metadatas"] and results["metadatas"][0]:
        for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
            templates.append({
                "question": meta["question"],
                "sql": meta["sql"],
                "distance": dist,
            })

    matched = [
        f"{t['question'][:40]}... ({t['distance']:.3f})" for t in templates
    ]
    logger.info(
        f"📋 Template match for '{query[:50]}...' → {matched}"
    )

    return templates
