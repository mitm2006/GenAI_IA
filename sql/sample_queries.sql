-- =============================================================
-- Sample Natural Language → SQL Pairs
-- For documentation and testing reference
-- =============================================================

-- Q: What were total sales in 2024?
SELECT SUM(total_amount) AS total_sales
FROM fact_sales fs
JOIN dim_date dd ON fs.date_id = dd.date_id
WHERE dd.year = 2024;

-- Q: Top 10 products by revenue
SELECT dp.product_name, SUM(fs.total_amount) AS revenue
FROM fact_sales fs
JOIN dim_product dp ON fs.product_id = dp.product_id
GROUP BY dp.product_name
ORDER BY revenue DESC
LIMIT 10;

-- Q: Monthly revenue trend for 2024
SELECT dd.month_name, dd.month, SUM(fs.total_amount) AS revenue
FROM fact_sales fs
JOIN dim_date dd ON fs.date_id = dd.date_id
WHERE dd.year = 2024
GROUP BY dd.month_name, dd.month
ORDER BY dd.month
LIMIT 12;

-- Q: Sales by customer segment
SELECT dc.segment, SUM(fs.total_amount) AS total_sales, COUNT(*) AS order_count
FROM fact_sales fs
JOIN dim_customer dc ON fs.customer_id = dc.customer_id
GROUP BY dc.segment
ORDER BY total_sales DESC
LIMIT 10;

-- Q: Top 5 cities by profit
SELECT dr.city, SUM(fs.profit) AS total_profit
FROM fact_sales fs
JOIN dim_region dr ON fs.region_id = dr.region_id
GROUP BY dr.city
ORDER BY total_profit DESC
LIMIT 5;

-- Q: Average discount by product category
SELECT dp.category, ROUND(AVG(fs.discount) * 100, 2) AS avg_discount_pct
FROM fact_sales fs
JOIN dim_product dp ON fs.product_id = dp.product_id
GROUP BY dp.category
ORDER BY avg_discount_pct DESC
LIMIT 20;

-- Q: Quarterly profit comparison for 2023 vs 2024
SELECT dd.year, dd.quarter, SUM(fs.profit) AS total_profit
FROM fact_sales fs
JOIN dim_date dd ON fs.date_id = dd.date_id
WHERE dd.year IN (2023, 2024)
GROUP BY dd.year, dd.quarter
ORDER BY dd.year, dd.quarter
LIMIT 20;

-- Q: Which shipping mode generates most revenue?
SELECT fs.ship_mode, SUM(fs.total_amount) AS revenue, COUNT(*) AS orders
FROM fact_sales fs
GROUP BY fs.ship_mode
ORDER BY revenue DESC
LIMIT 10;

-- Q: Customer loyalty tier distribution
SELECT dc.loyalty_tier, COUNT(*) AS customer_count
FROM dim_customer dc
GROUP BY dc.loyalty_tier
ORDER BY customer_count DESC
LIMIT 10;

-- Q: Top 10 customers by total spend
SELECT dc.first_name || ' ' || dc.last_name AS customer_name,
       dc.segment,
       SUM(fs.total_amount) AS total_spend
FROM fact_sales fs
JOIN dim_customer dc ON fs.customer_id = dc.customer_id
GROUP BY dc.customer_id, dc.first_name, dc.last_name, dc.segment
ORDER BY total_spend DESC
LIMIT 10;
