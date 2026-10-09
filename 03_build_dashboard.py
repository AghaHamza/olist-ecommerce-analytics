"""
Step 3: build a self-contained interactive dashboard (outputs/dashboard.html) from the SQL results.
Usage:  python 03_build_dashboard.py      (run 02_run_analysis.py first; needs internet to load Chart.js)
"""
import json, sqlite3
from pathlib import Path
import pandas as pd

OUT = Path("outputs"); Q = OUT / "query_results"
rd = lambda n: pd.read_csv(Q / f"{n}.csv")
con = sqlite3.connect(OUT / "olist.db")
k = con.execute("""SELECT COUNT(*), SUM(item_revenue), AVG(item_revenue), 100.0*AVG(is_late), AVG(review_score)
                   FROM order_facts WHERE order_status='delivered'""").fetchone()
rep = 100 - rd("repeat_customers").set_index("segment").loc["1 order", "pct_customers"]
kpis = [("Delivered orders", f"{k[0]:,}"), ("Revenue", f"R$ {k[1]:,.0f}"), ("Avg order value", f"R$ {k[2]:,.0f}"),
        ("Late deliveries", f"{k[3]:.1f}%"), ("Avg review", f"{k[4]:.2f} / 5"), ("Repeat customers", f"{rep:.1f}%")]

mr = rd("monthly_revenue"); mr = mr[mr.orders >= 50]
cr = rd("cohort_retention"); cr = cr[(cr.cohort_size >= 100) & (cr.months_since >= 1)]
cohort = {"rows": sorted(cr.cohort_month.unique().tolist()), "cols": list(range(1, 7)),
          "vals": {f"{r.cohort_month}|{r.months_since}": r.retention_pct for r in cr.itertuples()}}
data = {"kpis": kpis, "monthly": mr[["month", "revenue"]].to_dict("list"),
        "cats": rd("top_categories").head(10)[["category", "revenue"]].to_dict("list"),
        "states": rd("state_summary").sort_values("late_pct", ascending=False)[["state", "late_pct", "avg_review"]].to_dict("list"),
        "dvr": rd("delivery_vs_review")[["bucket", "avg_review", "pct_bad_reviews"]].to_dict("list"),
        "cohort": cohort, "sellers": rd("seller_scorecard").head(10).to_dict("records")}

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Olist E-commerce Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f8;color:#1f2937}
header{background:#1f3a5f;color:#fff;padding:20px 32px}h1{margin:0;font-size:24px}header p{margin:4px 0 0;opacity:.8}
.wrap{padding:24px 32px;max-width:1300px;margin:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px #0001}.kpi b{display:block;font-size:24px;margin-top:6px}
.kpi span{font-size:13px;color:#6b7280}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:18px}
.card{background:#fff;border-radius:10px;padding:18px;box-shadow:0 1px 3px #0001}.card h3{margin:0 0 10px;font-size:16px}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:6px 8px;text-align:right}th:first-child,td:first-child{text-align:left}
th{color:#6b7280;border-bottom:1px solid #e5e7eb}.wide{grid-column:1/-1}.scroll{overflow-x:auto}
</style></head><body>
<header><h1>Olist E-commerce Performance</h1><p>Delivered orders - revenue, delivery, satisfaction, retention</p></header>
<div class="wrap"><div class="kpis" id="kpis"></div><div class="grid">
<div class="card wide"><h3>Monthly revenue</h3><canvas id="c1" height="90"></canvas></div>
<div class="card"><h3>Top 10 categories by revenue</h3><canvas id="c2"></canvas></div>
<div class="card"><h3>Review score by delivery lateness</h3><canvas id="c3"></canvas></div>
<div class="card"><h3>Late-delivery rate by state (%)</h3><canvas id="c4"></canvas></div>
<div class="card"><h3>Worst sellers by late rate (min 20 orders)</h3><div class="scroll"><table id="t1"></table></div></div>
<div class="card wide"><h3>Cohort retention: % of cohort buying again, by months since first purchase</h3><div class="scroll"><table id="t2"></table></div></div>
</div></div>
<script>
const D = __DATA__;
document.getElementById('kpis').innerHTML = D.kpis.map(k=>`<div class="kpi"><span>${k[0]}</span><b>${k[1]}</b></div>`).join('');
const base={plugins:{legend:{display:false}}};
new Chart(c1,{type:'line',data:{labels:D.monthly.month,datasets:[{data:D.monthly.revenue,borderColor:'#2e86c1',backgroundColor:'#2e86c122',fill:true,tension:.25}]},options:base});
new Chart(c2,{type:'bar',data:{labels:D.cats.category,datasets:[{data:D.cats.revenue,backgroundColor:'#2e86c1'}]},options:{...base,indexAxis:'y'}});
new Chart(c3,{type:'bar',data:{labels:D.dvr.bucket,datasets:[{label:'Avg review',data:D.dvr.avg_review,backgroundColor:'#27ae60'},{label:'% 1-2 star',data:D.dvr.pct_bad_reviews,backgroundColor:'#c0392b'}]},options:{plugins:{legend:{display:true}}}});
new Chart(c4,{type:'bar',data:{labels:D.states.state,datasets:[{data:D.states.late_pct,backgroundColor:'#e67e22'}]},options:base});
t1.innerHTML='<tr><th>Seller</th><th>State</th><th>Orders</th><th>Late %</th><th>Avg review</th></tr>'+D.sellers.map(s=>`<tr><td>${s.seller_id.slice(0,10)}</td><td>${s.seller_state}</td><td>${s.orders}</td><td>${s.late_pct}</td><td>${s.avg_review}</td></tr>`).join('');
const mx=Math.max(...Object.values(D.cohort.vals),1);
t2.innerHTML='<tr><th>Cohort</th>'+D.cohort.cols.map(c=>`<th>M+${c}</th>`).join('')+'</tr>'+D.cohort.rows.map(r=>`<tr><td>${r}</td>`+D.cohort.cols.map(c=>{const v=D.cohort.vals[r+'|'+c];return v===undefined?'<td></td>':`<td style="background:rgba(46,134,193,${(v/mx*.85+.05).toFixed(2)})">${v.toFixed(1)}</td>`}).join('')+'</tr>').join('');
</script></body></html>"""
(OUT / "dashboard.html").write_text(HTML.replace("__DATA__", json.dumps(data, default=float)), encoding="utf-8")
print("Wrote", OUT / "dashboard.html", "- open it in your browser")
