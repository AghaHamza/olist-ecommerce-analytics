-- Olist analysis queries (SQLite). Each query is tagged with a name line so 02_run_analysis.py can run it.
-- Revenue = item price (excludes freight) on DELIVERED orders unless stated otherwise.

-- name: order_status_mix
SELECT order_status,
       COUNT(*) AS orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM orders
GROUP BY order_status
ORDER BY orders DESC;

-- name: monthly_revenue
WITH m AS (
    SELECT purchase_month AS month, COUNT(*) AS orders, SUM(item_revenue) AS revenue
    FROM order_facts
    WHERE order_status = 'delivered'
    GROUP BY purchase_month
)
SELECT month, orders,
       ROUND(revenue, 2)                                   AS revenue,
       ROUND(revenue / orders, 2)                          AS avg_order_value,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 1)      AS mom_growth_pct,
       ROUND(SUM(revenue) OVER (ORDER BY month), 2)        AS cumulative_revenue
FROM m
ORDER BY month;

-- name: top_categories
WITH cat AS (
    SELECT COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
           COUNT(DISTINCT oi.order_id) AS orders,
           SUM(oi.price)               AS revenue,
           AVG(oi.price)               AS avg_price
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id AND o.order_status = 'delivered'
    LEFT JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
    GROUP BY 1
)
SELECT category, orders,
       ROUND(revenue, 2)                               AS revenue,
       ROUND(avg_price, 2)                             AS avg_price,
       ROUND(100.0 * revenue / SUM(revenue) OVER (), 2) AS revenue_share_pct,
       RANK() OVER (ORDER BY revenue DESC)             AS revenue_rank
FROM cat
ORDER BY revenue DESC
LIMIT 15;

-- name: state_summary
SELECT customer_state AS state,
       COUNT(*)                          AS orders,
       ROUND(SUM(item_revenue), 2)       AS revenue,
       ROUND(AVG(delivery_days), 1)      AS avg_delivery_days,
       ROUND(100.0 * AVG(is_late), 1)    AS late_pct,
       ROUND(AVG(review_score), 2)       AS avg_review
FROM order_facts
WHERE order_status = 'delivered' AND delivered_ts IS NOT NULL
GROUP BY customer_state
HAVING COUNT(*) >= 30
ORDER BY revenue DESC;

-- name: delivery_vs_review
WITH b AS (
    SELECT review_score,
           CASE WHEN days_late <= 0 THEN '1. On time or early'
                WHEN days_late <= 3 THEN '2. 1-3 days late'
                WHEN days_late <= 7 THEN '3. 4-7 days late'
                ELSE '4. 8+ days late' END AS bucket
    FROM order_facts
    WHERE order_status = 'delivered' AND delivered_ts IS NOT NULL AND review_score IS NOT NULL
)
SELECT bucket,
       COUNT(*)                                                       AS orders,
       ROUND(AVG(review_score), 2)                                    AS avg_review,
       ROUND(100.0 * AVG(CASE WHEN review_score <= 2 THEN 1.0 ELSE 0 END), 1) AS pct_bad_reviews
FROM b
GROUP BY bucket
ORDER BY bucket;

-- name: repeat_customers
WITH per_cust AS (
    SELECT customer_unique_id, COUNT(*) AS n_orders, SUM(item_revenue) AS revenue
    FROM order_facts
    WHERE order_status = 'delivered'
    GROUP BY customer_unique_id
)
SELECT CASE WHEN n_orders = 1 THEN '1 order' WHEN n_orders = 2 THEN '2 orders' ELSE '3+ orders' END AS segment,
       COUNT(*)                                                    AS customers,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)          AS pct_customers,
       ROUND(SUM(revenue), 2)                                      AS revenue,
       ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2)  AS pct_revenue
FROM per_cust
GROUP BY 1
ORDER BY MIN(n_orders);

-- name: cohort_retention
WITH orders_m AS (
    SELECT customer_unique_id,
           CAST(substr(purchase_month, 1, 4) AS INT) * 12 + CAST(substr(purchase_month, 6, 2) AS INT) AS m
    FROM order_facts
    WHERE order_status = 'delivered'
),
first_purchase AS (
    SELECT customer_unique_id, MIN(m) AS first_m FROM orders_m GROUP BY customer_unique_id
),
activity AS (
    SELECT DISTINCT o.customer_unique_id, f.first_m, o.m - f.first_m AS months_since
    FROM orders_m o JOIN first_purchase f USING (customer_unique_id)
),
cohort_size AS (
    SELECT first_m, COUNT(*) AS size FROM first_purchase GROUP BY first_m
)
SELECT printf('%d-%02d', (a.first_m - 1) / 12, (a.first_m - 1) % 12 + 1) AS cohort_month,
       c.size                                       AS cohort_size,
       a.months_since,
       COUNT(*)                                     AS active_customers,
       ROUND(100.0 * COUNT(*) / c.size, 2)          AS retention_pct
FROM activity a
JOIN cohort_size c ON c.first_m = a.first_m
WHERE a.months_since BETWEEN 0 AND 6
GROUP BY a.first_m, a.months_since
ORDER BY a.first_m, a.months_since;

-- name: payment_types
SELECT p.payment_type,
       COUNT(DISTINCT p.order_id)           AS orders,
       ROUND(SUM(p.payment_value), 2)       AS total_value,
       ROUND(AVG(p.payment_value), 2)       AS avg_payment,
       ROUND(AVG(p.payment_installments), 2) AS avg_installments
FROM order_payments p
JOIN orders o ON o.order_id = p.order_id
WHERE o.order_status = 'delivered'
GROUP BY p.payment_type
ORDER BY total_value DESC;

-- name: seller_scorecard
WITH seller_orders AS (
    SELECT oi.seller_id, oi.order_id, SUM(oi.price) AS revenue
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id AND o.order_status = 'delivered'
    GROUP BY oi.seller_id, oi.order_id
),
seller_stats AS (
    SELECT so.seller_id,
           COUNT(*)               AS orders,
           SUM(so.revenue)        AS revenue,
           AVG(f.is_late) * 100   AS late_pct,
           AVG(f.review_score)    AS avg_review
    FROM seller_orders so
    JOIN order_facts f ON f.order_id = so.order_id
    GROUP BY so.seller_id
    HAVING COUNT(*) >= 20
)
SELECT s.seller_id, sl.seller_state, s.orders,
       ROUND(s.revenue, 2)    AS revenue,
       ROUND(s.late_pct, 1)   AS late_pct,
       ROUND(s.avg_review, 2) AS avg_review,
       RANK() OVER (ORDER BY s.late_pct DESC) AS lateness_rank
FROM seller_stats s
JOIN sellers sl ON sl.seller_id = s.seller_id
ORDER BY s.late_pct DESC
LIMIT 15;
