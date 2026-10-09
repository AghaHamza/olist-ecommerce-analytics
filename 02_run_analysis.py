"""
Step 2: run every SQL query, VALIDATE against an independent pandas calculation from the raw CSVs,
save charts and an auto-generated findings.md.
Usage:  python 02_run_analysis.py [path/to/csv/folder]     (run 01_build_database.py first)
"""
import re, sqlite3, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd, seaborn as sns

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
OUT = Path("outputs"); (OUT / "charts").mkdir(parents=True, exist_ok=True); (OUT / "query_results").mkdir(exist_ok=True)
sns.set_theme(style="whitegrid", context="talk")
con = sqlite3.connect(OUT / "olist.db")

# ------------------------------------------------------------------ run SQL
sql = Path("sql/02_analysis_queries.sql").read_text()
queries = {m.group(1): m.group(2).strip() for m in
           re.finditer(r"^-- name: (\w+)[^\n]*\n(.*?)(?=^-- name:|\Z)", sql, re.S | re.M)}
R = {}
for name, q in queries.items():
    R[name] = pd.read_sql_query(q, con)
    R[name].to_csv(OUT / "query_results" / f"{name}.csv", index=False)
    print(f"\n--- {name} ({len(R[name])} rows) ---\n{R[name].head(6).to_string(index=False)}")

# ------------------------------------------------------------------ pandas validation (from RAW csvs, not the DB)
print("\n" + "=" * 70 + "\nVALIDATION: SQL vs independent pandas calculation\n" + "=" * 70)
rd = lambda f: pd.read_csv(DATA / f)
orders = rd("olist_orders_dataset.csv"); items = rd("olist_order_items_dataset.csv")
pays = rd("olist_order_payments_dataset.csv"); revs = rd("olist_order_reviews_dataset.csv")
cust = rd("olist_customers_dataset.csv")
for c in ["order_purchase_timestamp", "order_delivered_customer_date", "order_estimated_delivery_date"]:
    orders[c] = pd.to_datetime(orders[c])
orders["month"] = orders["order_purchase_timestamp"].dt.strftime("%Y-%m")
rev_per_order = items.groupby("order_id")["price"].sum().rename("rev")
od = orders.merge(rev_per_order, on="order_id", how="left").merge(cust[["customer_id", "customer_unique_id", "customer_state"]], on="customer_id")
od["rev"] = od["rev"].fillna(0)
d = od[od.order_status == "delivered"].copy()

checks = []
def check(label, a, b, tol=0.05):
    ok = np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)
    checks.append(ok); print(f"[{'PASS' if ok else 'FAIL'}] {label}")

check("Order count by status", R["order_status_mix"].set_index("order_status")["orders"].sort_index(),
      orders["order_status"].value_counts().sort_index(), tol=0)
check("Total delivered revenue (monthly sum)", [R["monthly_revenue"]["revenue"].sum()], [d["rev"].sum()], tol=1)
m = d.groupby("month")["rev"].sum(); mm = R["monthly_revenue"].set_index("month")["revenue"]
check("Monthly revenue, every month", mm, m.loc[mm.index], tol=0.1)
check("Revenue by category sums to total delivered revenue",
      [pd.read_sql_query("SELECT SUM(oi.price) FROM order_items oi JOIN orders o USING(order_id) WHERE o.order_status='delivered'", con).iloc[0, 0]],
      [d["rev"].sum()], tol=1)
check("Payments total (delivered) matches", [R["payment_types"]["total_value"].sum()],
      [pays[pays.order_id.isin(d.order_id)]["payment_value"].sum()], tol=1)

dd = d[d.order_delivered_customer_date.notna()].copy()
dd["late"] = (dd.order_delivered_customer_date.dt.normalize() > dd.order_estimated_delivery_date.dt.normalize()).astype(int)
s = R["state_summary"].set_index("state"); g = dd.groupby("customer_state")["late"].mean() * 100
check("Late-delivery % by state", s["late_pct"], g.loc[s.index], tol=0.06)
check("Orders by state", s["orders"], dd.groupby("customer_state").size().loc[s.index], tol=0)

rv = revs.groupby("order_id")["review_score"].mean().rename("score")
dd = dd.merge(rv, on="order_id")
dd["late_days"] = (dd.order_delivered_customer_date.dt.normalize() - dd.order_estimated_delivery_date.dt.normalize()).dt.days
dd["bucket"] = pd.cut(dd.late_days, [-1e9, 0, 3, 7, 1e9], labels=["1. On time or early", "2. 1-3 days late", "3. 4-7 days late", "4. 8+ days late"])
b = dd.groupby("bucket", observed=True)["score"].mean(); sb = R["delivery_vs_review"].set_index("bucket")
check("Avg review score by lateness bucket", sb["avg_review"], b.loc[sb.index], tol=0.006)

per_c = d.groupby("customer_unique_id").size()
check("Customers who ordered once / repeat", R["repeat_customers"]["customers"].values,
      [(per_c == 1).sum(), (per_c == 2).sum(), (per_c >= 3).sum()][:len(R["repeat_customers"])], tol=0)
first = d.groupby("customer_unique_id")["month"].min().value_counts()
cs = R["cohort_retention"].drop_duplicates("cohort_month").set_index("cohort_month")["cohort_size"]
check("Cohort sizes", cs, first.loc[cs.index], tol=0)
check("Retention at month 0 is 100%", R["cohort_retention"].query("months_since == 0")["retention_pct"], [100.0] * int((R["cohort_retention"].months_since == 0).sum()), tol=0.01)
fan = con.execute("SELECT (SELECT COUNT(*) FROM order_facts), (SELECT COUNT(*) FROM orders)").fetchone()
check("order_facts has exactly one row per order (no join fan-out)", [fan[0]], [fan[1]], tol=0)
print(f"\n{sum(checks)}/{len(checks)} checks passed")

# ------------------------------------------------------------------ charts
C = OUT / "charts"; fmt = matplotlib.ticker.FuncFormatter(lambda x, _: f"{x/1000:,.0f}k")
mr = R["monthly_revenue"]; mr = mr[mr.orders >= 50]       # tiny first/last months distort the trend
fig, ax = plt.subplots(figsize=(13, 6)); ax.plot(pd.to_datetime(mr.month), mr.revenue, marker="o", lw=2)
ax.set(title="Monthly Revenue (delivered orders)", ylabel="Revenue"); ax.yaxis.set_major_formatter(fmt)
fig.tight_layout(); fig.savefig(C / "1_monthly_revenue.png", dpi=150); plt.close(fig)

tc = R["top_categories"].head(10).iloc[::-1]
fig, ax = plt.subplots(figsize=(11, 7)); ax.barh(tc.category, tc.revenue, color="#2e86c1")
ax.set(title="Top 10 Categories by Revenue", xlabel="Revenue"); ax.xaxis.set_major_formatter(fmt)
fig.tight_layout(); fig.savefig(C / "2_top_categories.png", dpi=150); plt.close(fig)

dv = R["delivery_vs_review"]
fig, ax = plt.subplots(1, 2, figsize=(15, 6))
sns.barplot(data=dv, x="bucket", y="avg_review", ax=ax[0], color="#2e86c1"); ax[0].set(title="Average review score", xlabel="", ylabel="Score (1-5)", ylim=(0, 5))
sns.barplot(data=dv, x="bucket", y="pct_bad_reviews", ax=ax[1], color="#c0392b"); ax[1].set(title="% of 1-2 star reviews", xlabel="", ylabel="%")
for a in ax: a.tick_params(axis="x", rotation=20)
fig.suptitle("Late delivery vs customer satisfaction"); fig.tight_layout(); fig.savefig(C / "3_delivery_vs_review.png", dpi=150); plt.close(fig)

ss = R["state_summary"].sort_values("late_pct", ascending=False)
fig, ax = plt.subplots(figsize=(12, 6)); sns.barplot(data=ss, x="state", y="late_pct", color="#e67e22", ax=ax)
ax.set(title="Late-delivery rate by customer state", ylabel="% of orders late", xlabel="")
fig.tight_layout(); fig.savefig(C / "4_late_by_state.png", dpi=150); plt.close(fig)

cr = R["cohort_retention"]; cr = cr[cr.cohort_size >= 100]
pv = cr[cr.months_since >= 1].pivot(index="cohort_month", columns="months_since", values="retention_pct")
fig, ax = plt.subplots(figsize=(11, 9)); sns.heatmap(pv, annot=True, fmt=".1f", cmap="Blues", ax=ax, cbar_kws={"label": "% of cohort buying again"})
ax.set(title="Cohort retention (months after first purchase)", xlabel="Months since first purchase", ylabel="First-purchase month")
fig.tight_layout(); fig.savefig(C / "5_cohort_retention.png", dpi=150); plt.close(fig)
print("\nSaved 5 charts to", C)

# ------------------------------------------------------------------ findings
rc = R["repeat_customers"].set_index("segment"); rep_pct = 100 - rc.loc["1 order", "pct_customers"]
ontime, worst = dv.iloc[0], dv.iloc[-1]
t1 = R["top_categories"].iloc[0]; top3 = R["top_categories"].head(3)["revenue_share_pct"].sum()
worst_state = ss.iloc[0]; best_state = ss.iloc[-1]
overall_late = 100 * dd["late"].mean()
delivery_note = " (strong link)" if ontime.avg_review - worst.avg_review >= 1 else " (weak link)"
repeat_note = " is the weak spot" if rep_pct < 10 else " is healthy"
md = f"""# Olist E-commerce - Key Findings (auto-generated; rewrite in your own words)

1. **Delivery vs satisfaction{delivery_note}.** On-time orders average {ontime.avg_review:.2f} stars; orders 8+ days late average {worst.avg_review:.2f}
   ({worst.pct_bad_reviews:.0f}% are 1-2 star vs {ontime.pct_bad_reviews:.0f}% when on time). {overall_late:.1f}% of delivered orders arrive after the estimate.
2. **Repeat purchasing{repeat_note}.** {rep_pct:.1f}% of customers ordered more than once; one-time buyers generate {rc.loc['1 order', 'pct_revenue']:.1f}% of revenue.
3. **Revenue concentration.** {t1.category} is #1 ({t1.revenue_share_pct:.1f}% of revenue); the top 3 categories make up {top3:.1f}%.
4. **Regional logistics gap.** {worst_state.state} has the highest late rate ({worst_state.late_pct:.1f}%) vs {best_state.state} ({best_state.late_pct:.1f}%).
5. **Payments.** {R['payment_types'].iloc[0].payment_type} accounts for the largest share of payment value.

## Recommendations to investigate (edit these)
- Improve delivery-date promises/carrier performance in the worst states; set realistic ETAs - lateness costs ratings.
- Review the sellers with the highest late rates (see seller_scorecard) for coaching or removal.
- Repeat purchase rate is {rep_pct:.1f}%: judge whether a post-purchase retention test (email/voucher after delivery) is worth running.
- Check whether high-revenue categories are also the late-delivery or low-review ones.

## Limitations
Observational data: late delivery and low scores are associated, not proven causal. Cohort months with few customers are noisy.
"""
(OUT / "findings.md").write_text(md, encoding="utf-8"); print("Wrote", OUT / "findings.md")
con.close()
