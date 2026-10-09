"""
Step 1: load the 8 Olist CSVs, run data-quality checks, build a SQLite database + the order_facts view.
Usage:  python 01_build_database.py [path/to/csv/folder]     (default folder: ./data)
"""
import sqlite3, sys
from pathlib import Path
import pandas as pd

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
OUT = Path("outputs"); OUT.mkdir(exist_ok=True)

FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}
missing = [f for f in FILES.values() if not (DATA / f).exists()]
if missing:
    sys.exit(f"Missing files in '{DATA}': {missing}\nDownload the Olist dataset from Kaggle and unzip it there.")

T = {name: pd.read_csv(DATA / f) for name, f in FILES.items()}

print("=" * 70, "\nDATA QUALITY REPORT\n" + "=" * 70)
for name, df in T.items():
    print(f"{name:22s} rows={len(df):>8,}  cols={df.shape[1]:>2}  "
          f"null cells={int(df.isna().sum().sum()):>8,}  full-row duplicates={int(df.duplicated().sum())}")

o = T["orders"]
for c in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
          "order_delivered_customer_date", "order_estimated_delivery_date"]:
    o[c] = pd.to_datetime(o[c], errors="coerce")
print("\nOrder status mix:\n", o["order_status"].value_counts().to_string())

deliv = o[o["order_status"] == "delivered"]
print(f"\nDelivered orders with NO delivery date: {deliv['order_delivered_customer_date'].isna().sum()}")
print(f"Delivered before purchase (impossible):  {(deliv['order_delivered_customer_date'] < deliv['order_purchase_timestamp']).sum()}")
print(f"Orders with no items:                    {(~o['order_id'].isin(T['order_items']['order_id'])).sum()}")
print(f"Orders with several reviews:             {(T['order_reviews'].groupby('order_id').size() > 1).sum()}")
print(f"Orders with several payment rows:        {(T['order_payments'].groupby('order_id').size() > 1).sum()}")
print(f"Customers: {T['customers']['customer_id'].nunique():,} customer_ids but only "
      f"{T['customers']['customer_unique_id'].nunique():,} unique people -> use customer_unique_id for repeat analysis")
p, tr = T["products"], T["category_translation"]
print(f"Products with no category: {p['product_category_name'].isna().sum()}; "
      f"categories missing an English translation: {(~p['product_category_name'].dropna().isin(tr['product_category_name'])).sum()} products")
print("\nDecisions: keep all rows (flag, don't delete); revenue analysed on delivered orders only; "
      "reviews/payments/items aggregated per order before joining.")

# timestamps -> ISO text so SQLite date functions work
for c in o.columns:
    if c.startswith("order_") and c != "order_status" and c != "order_id":
        o[c] = o[c].dt.strftime("%Y-%m-%d %H:%M:%S")
T["orders"] = o

db = OUT / "olist.db"
if db.exists(): db.unlink()
con = sqlite3.connect(db)
for name, df in T.items():
    df.to_sql(name, con, index=False)
for stmt in ["CREATE INDEX ix_items_order ON order_items(order_id)",
             "CREATE INDEX ix_items_seller ON order_items(seller_id)",
             "CREATE INDEX ix_pay_order ON order_payments(order_id)",
             "CREATE INDEX ix_rev_order ON order_reviews(order_id)",
             "CREATE INDEX ix_orders_cust ON orders(customer_id)",
             "CREATE INDEX ix_cust_id ON customers(customer_id)"]:
    con.execute(stmt)
con.executescript(Path("sql/01_order_facts_view.sql").read_text())
n = con.execute("SELECT COUNT(*) FROM order_facts").fetchone()[0]
print(f"\nDatabase built: {db}  |  order_facts rows = {n:,} (orders = {len(o):,}) "
      f"{'OK - no fan-out' if n == len(o) else 'WARNING: join fan-out!'}")
con.commit(); con.close()
