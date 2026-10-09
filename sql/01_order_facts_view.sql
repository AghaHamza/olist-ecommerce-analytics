-- One row per order. Items, payments and reviews are each aggregated to ONE row per order
-- BEFORE joining. Joining the raw tables directly would multiply rows (fan-out) and inflate revenue,
-- because an order can have several items, several payment rows and occasionally several reviews.
DROP VIEW IF EXISTS order_facts;
CREATE VIEW order_facts AS
WITH items AS (
    SELECT order_id, COUNT(*) AS n_items, SUM(price) AS item_revenue, SUM(freight_value) AS freight
    FROM order_items GROUP BY order_id
),
pay AS (
    SELECT order_id, SUM(payment_value) AS paid, MAX(payment_installments) AS max_installments
    FROM order_payments GROUP BY order_id
),
rev AS (
    SELECT order_id, AVG(review_score) AS review_score
    FROM order_reviews GROUP BY order_id
)
SELECT o.order_id,
       o.customer_id,
       c.customer_unique_id,                       -- the real person (customer_id is new per order!)
       c.customer_state,
       o.order_status,
       o.order_purchase_timestamp                         AS purchase_ts,
       strftime('%Y-%m', o.order_purchase_timestamp)      AS purchase_month,
       o.order_delivered_customer_date                    AS delivered_ts,
       o.order_estimated_delivery_date                    AS estimated_ts,
       i.n_items,
       COALESCE(i.item_revenue, 0)                        AS item_revenue,
       COALESCE(i.freight, 0)                             AS freight,
       p.paid, p.max_installments, r.review_score,
       julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) AS delivery_days,
       julianday(date(o.order_delivered_customer_date)) - julianday(date(o.order_estimated_delivery_date)) AS days_late,
       CASE WHEN o.order_delivered_customer_date IS NULL THEN NULL
            WHEN date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date) THEN 1
            ELSE 0 END                                    AS is_late
FROM orders o
JOIN customers c   ON c.customer_id = o.customer_id
LEFT JOIN items i  ON i.order_id = o.order_id
LEFT JOIN pay p    ON p.order_id = o.order_id
LEFT JOIN rev r    ON r.order_id = o.order_id;
