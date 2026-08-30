# Architecture Documentation

## System Architecture Diagram

```mermaid
graph TD
    A["👤 User (React SPA)"] -->|"Natural Language Question"| B["FastAPI /api/query"]
    B --> C["Schema Retrieval"]
    C -->|"Embed question"| D["ChromaDB"]
    D -->|"Top-K relevant tables"| E["Prompt Builder"]
    E -->|"Schema-aware prompt"| F["LLM Service → Groq<br/>openai/gpt-oss-20b"]
    F -->|"Final answer only<br/>(reasoning suppressed)"| G["SQL Validator (8 layers)"]
    G -->|"Valid SQL"| H["Confidence Scorer"]
    H --> I["Query Executor (Read-Only)"]
    I -->|"Success"| J["Auto-Visualization (Plotly)"]
    I -->|"Failure"| K["Auto-Retry Engine"]
    K -->|"Corrected SQL"| G
    J --> L["Insight Generator (LLM)"]
    L --> M["JSON Response to React UI"]

    style A fill:#6366f1,stroke:#4f46e5,color:#fff
    style F fill:#8b5cf6,stroke:#7c3aed,color:#fff
    style G fill:#ef4444,stroke:#dc2626,color:#fff
    style J fill:#06b6d4,stroke:#0891b2,color:#fff
```

## Data Flow

```mermaid
sequenceDiagram
    participant U as User
    participant S as React SPA
    participant A as FastAPI
    participant C as ChromaDB
    participant L as Groq (gpt-oss-20b)
    participant V as Validator
    participant D as PostgreSQL

    U->>S: "Top 10 products by revenue"
    S->>A: POST /api/query
    A->>C: Embed question → find relevant tables
    C-->>A: fact_sales, dim_product metadata
    A->>L: Schema-aware prompt
    L-->>A: SELECT dp.product_name, SUM(fs.total_amount)... (final channel only)
    A->>V: Validate SQL (8 layers)
    V-->>A: ✅ Valid (score: 92%)
    A->>D: Execute (read-only, 10s timeout)
    D-->>A: 10 rows
    A->>A: Generate business insight (code-based, no LLM call)
    A-->>S: SQL + Data + Chart + Insight
    S-->>U: 📊 Bar chart + 💡 Insight
```

## Database Star Schema

```mermaid
erDiagram
    dim_date {
        int date_id PK
        date full_date
        int month
        varchar month_name
        int quarter
        int year
        boolean is_weekend
    }

    dim_region {
        int region_id PK
        varchar region_name
        varchar country
        varchar state
        varchar city
    }

    dim_customer {
        int customer_id PK
        varchar first_name
        varchar last_name
        varchar segment
        varchar loyalty_tier
        int region_id FK
    }

    dim_product {
        int product_id PK
        varchar product_name
        varchar category
        varchar sub_category
        varchar brand
        numeric unit_price
    }

    fact_sales {
        int sale_id PK
        varchar order_number
        int customer_id FK
        int product_id FK
        int date_id FK
        int region_id FK
        int quantity
        numeric total_amount
        numeric profit
        varchar ship_mode
    }

    fact_sales ||--o{ dim_customer : "customer_id"
    fact_sales ||--o{ dim_product : "product_id"
    fact_sales ||--o{ dim_date : "date_id"
    fact_sales ||--o{ dim_region : "region_id"
    dim_customer ||--o{ dim_region : "region_id"
```

## Security Architecture

| Layer | Protection |
|-------|-----------|
| SQL Validation | SELECT-only, blocked DDL/DML, injection pattern detection |
| LIMIT Enforcement | Auto-adds LIMIT, caps at 1000 rows |
| Read-Only DB User | `bi_readonly` role with SELECT-only privileges |
| Statement Timeout | 10-second PostgreSQL timeout per query |
| Schema Validation | Rejects queries referencing unknown tables/columns |
| Input Sanitization | sqlparse structural validation, stacked query rejection |
