-- =============================================================
-- LLM-Powered BI SQL Assistant — Star Schema DDL
-- PostgreSQL Analytics Database
-- =============================================================

-- ─── Dimension: Date ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_date (
    date_id         SERIAL PRIMARY KEY,
    full_date       DATE        NOT NULL UNIQUE,
    day_of_month    SMALLINT    NOT NULL,
    day_of_week     SMALLINT    NOT NULL,  -- 0=Mon … 6=Sun
    day_name        VARCHAR(10) NOT NULL,  -- Monday, Tuesday …
    week_of_year    SMALLINT    NOT NULL,
    month           SMALLINT    NOT NULL,
    month_name      VARCHAR(10) NOT NULL,
    quarter         SMALLINT    NOT NULL,
    year            SMALLINT    NOT NULL,
    is_weekend      BOOLEAN     NOT NULL DEFAULT FALSE,
    fiscal_quarter  SMALLINT    NOT NULL   -- companies often differ
);

CREATE INDEX idx_dim_date_full   ON dim_date(full_date);
CREATE INDEX idx_dim_date_year   ON dim_date(year);
CREATE INDEX idx_dim_date_month  ON dim_date(year, month);

-- ─── Dimension: Region ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_region (
    region_id       SERIAL PRIMARY KEY,
    region_name     VARCHAR(50)  NOT NULL,  -- North, South, East, West
    country         VARCHAR(60)  NOT NULL,
    state           VARCHAR(60)  NOT NULL,
    city            VARCHAR(80)  NOT NULL,
    postal_code     VARCHAR(15)  NOT NULL
);

CREATE INDEX idx_dim_region_name ON dim_region(region_name);
CREATE INDEX idx_dim_region_state ON dim_region(state);

-- ─── Dimension: Customer ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_customer (
    customer_id     SERIAL PRIMARY KEY,
    first_name      VARCHAR(50)  NOT NULL,
    last_name       VARCHAR(50)  NOT NULL,
    email           VARCHAR(120) NOT NULL UNIQUE,
    segment         VARCHAR(30)  NOT NULL
                        CHECK (segment IN ('Consumer', 'Corporate', 'Home Office', 'Small Business')),
    loyalty_tier    VARCHAR(20)  NOT NULL DEFAULT 'Bronze'
                        CHECK (loyalty_tier IN ('Bronze', 'Silver', 'Gold', 'Platinum')),
    join_date       DATE         NOT NULL,
    region_id       INTEGER      NOT NULL REFERENCES dim_region(region_id)
);

CREATE INDEX idx_dim_customer_segment ON dim_customer(segment);
CREATE INDEX idx_dim_customer_loyalty ON dim_customer(loyalty_tier);

-- ─── Dimension: Product ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS dim_product (
    product_id      SERIAL PRIMARY KEY,
    product_name    VARCHAR(150) NOT NULL,
    category        VARCHAR(50)  NOT NULL,
    sub_category    VARCHAR(50)  NOT NULL,
    brand           VARCHAR(60)  NOT NULL,
    unit_cost       NUMERIC(10,2) NOT NULL CHECK (unit_cost >= 0),
    unit_price      NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0)
);

CREATE INDEX idx_dim_product_cat ON dim_product(category);
CREATE INDEX idx_dim_product_subcat ON dim_product(sub_category);
CREATE INDEX idx_dim_product_brand ON dim_product(brand);

-- ─── Fact: Sales ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fact_sales (
    sale_id         SERIAL PRIMARY KEY,
    order_number    VARCHAR(20)  NOT NULL,
    customer_id     INTEGER      NOT NULL REFERENCES dim_customer(customer_id),
    product_id      INTEGER      NOT NULL REFERENCES dim_product(product_id),
    date_id         INTEGER      NOT NULL REFERENCES dim_date(date_id),
    region_id       INTEGER      NOT NULL REFERENCES dim_region(region_id),
    quantity        INTEGER      NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10,2) NOT NULL CHECK (unit_price >= 0),
    discount        NUMERIC(5,2) NOT NULL DEFAULT 0.00
                        CHECK (discount >= 0 AND discount <= 1),
    total_amount    NUMERIC(12,2) NOT NULL,
    cost            NUMERIC(12,2) NOT NULL,
    profit          NUMERIC(12,2) NOT NULL,
    ship_mode       VARCHAR(30)  NOT NULL
                        CHECK (ship_mode IN ('Standard', 'Express', 'Same Day', 'Economy'))
);

CREATE INDEX idx_fact_sales_date     ON fact_sales(date_id);
CREATE INDEX idx_fact_sales_customer ON fact_sales(customer_id);
CREATE INDEX idx_fact_sales_product  ON fact_sales(product_id);
CREATE INDEX idx_fact_sales_region   ON fact_sales(region_id);
CREATE INDEX idx_fact_sales_order    ON fact_sales(order_number);

-- ─── Read-Only Role ──────────────────────────────────────────
-- This role is used by the application for query execution.
-- It can only SELECT — no INSERT, UPDATE, DELETE, or DDL.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_readonly') THEN
        CREATE ROLE bi_readonly WITH LOGIN PASSWORD 'readonly_password';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE bi_analytics TO bi_readonly;
GRANT USAGE ON SCHEMA public TO bi_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bi_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO bi_readonly;
