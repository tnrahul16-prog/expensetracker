# app.py — single-file Expense Tracker with rich UI and 10 extra features
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash
import sqlite3, os, io, csv
from datetime import datetime, timedelta
import json

app = Flask(__name__)
app.secret_key = "replace-this-with-random-secret"   # for flash messages
DB = "expenses_full_singlefile.db"

# ----------------- Database helpers -----------------
def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT NOT NULL,
        amount REAL NOT NULL,
        date TEXT NOT NULL,
        category TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS recurring (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item TEXT NOT NULL,
        amount REAL NOT NULL,
        start_date TEXT NOT NULL,
        freq TEXT NOT NULL, -- 'monthly' supported
        last_applied TEXT,
        category TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    conn.close()

def query(query, args=(), one=False):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    conn.commit()
    conn.close()
    return (rv[0] if rv else None) if one else rv

# ----------------- Recurring helper -----------------
def apply_recurring():
    """Apply recurring monthly items up to today."""
    rows = query("SELECT * FROM recurring")
    today = datetime.today().date()
    for r in rows:
        # determine last applied date
        last = r["last_applied"] or r["start_date"]
        last_dt = datetime.strptime(last, "%Y-%m-%d").date()
        # If start date > today skip
        if last_dt > today:
            continue
        # apply monthly occurrences until up-to-date
        # Advance by calendar months properly:
        def add_months(dt, months):
            month = dt.month - 1 + months
            year = dt.year + month // 12
            month = month % 12 + 1
            day = min(dt.day, [31,29 if year%4==0 and (year%100!=0 or year%400==0) else 28,31,30,31,30,31,31,30,31,30,31][month-1])
            return datetime(year, month, day).date()
        next_dt = add_months(last_dt, 1)
        applied_any = False
        while next_dt <= today:
            # insert into expenses
            query("INSERT INTO expenses (item, amount, date, category) VALUES (?, ?, ?, ?)",
                  (r["item"], r["amount"], next_dt.isoformat(), r["category"]))
            # update last_applied
            query("UPDATE recurring SET last_applied=? WHERE id=?", (next_dt.isoformat(), r["id"]))
            applied_any = True
            last_dt = next_dt
            next_dt = add_months(last_dt, 1)
        # commit is inside query
    return

# ----------------- Utility -----------------
def get_setting(key):
    row = query("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return row["value"] if row else None

def set_setting(key, value):
    query("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(value)))

# ----------------- UI wrapper -----------------
def render_layout(content, title="Expense Tracker"):
    # content must be HTML-safe string
    # prepare flash messages
    flashes_html = ""
    # Inline template (using render_template_string will substitute these)
    template = f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <title>{title}</title>
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;500;700&display=swap" rel="stylesheet">
      <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
      <style>
        :root{{--accent:#6C5CE7;--accent-2:#00B894;--card:#ffffffcc;--muted:#718096;}}
        *{{box-sizing:border-box}}
        body{{font-family:'Poppins',sans-serif;margin:0;background:linear-gradient(135deg,#f6f8ff,#eaf6f1);color:#222;}}
        header{{background:linear-gradient(90deg,#6C5CE7,#00B894);color:#fff;padding:22px 0;box-shadow:0 6px 20px rgba(16,24,40,0.08)}}
        .wrap{{max-width:1100px;margin: -28px auto 40px;padding:24px}}
        .brand{{display:flex;align-items:center;gap:14px}}
        .brand i{{font-size:30px}}
        nav{{
            margin-top:14px; display:flex; gap:10px; flex-wrap:wrap;
        }}
        .nav-btn{{background:var(--card);padding:10px 14px;border-radius:10px;color:#111;text-decoration:none;font-weight:600;display:inline-flex;gap:8px;align-items:center;box-shadow:0 6px 18px rgba(0,0,0,0.06)}}
        .nav-btn:hover{{transform:translateY(-3px)}}
        .container{{max-width:1100px;margin:20px auto;padding:20px}}
        .grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:18px}}
        .card{{grid-column:span 12;background:var(--card);padding:18px;border-radius:12px;box-shadow:0 10px 30px rgba(2,6,23,0.06)}}
        .row{{display:flex;gap:12px;flex-wrap:wrap}}
        .col{{flex:1}}
        form input, form select {{width:100%;padding:10px;border-radius:8px;border:1px solid #e6e9ef;margin-top:6px}}
        button.btn{{background:var(--accent);color:#fff;padding:10px 14px;border-radius:10px;border:0;font-weight:700;cursor:pointer}}
        button.btn.alt{{background:#fff;color:var(--accent);border:2px solid var(--accent)}}
        table{{width:100%;border-collapse:collapse;margin-top:14px}}
        th,td{{padding:10px;text-align:left;border-bottom:1px solid #f1f3f6}}
        th{{background:#fafafa}}
        .stats{{display:flex;gap:12px;flex-wrap:wrap;}}
        .stat{{background:#fff;padding:12px;border-radius:10px;min-width:140px;box-shadow:0 6px 18px rgba(0,0,0,0.04)}}
        .muted{{color:var(--muted);font-size:0.95rem}}
        .danger{{color:#e74c3c}}
        .ok{{color:#16a085}}
        .small{{font-size:0.9rem;color:var(--muted)}}
      </style>
    </head>
    <body>
      <header>
        <div class="wrap">
          <div class="brand">
            <i class="fa-solid fa-wallet"></i>
            <div>
              <div style="font-weight:700;font-size:18px">Expense Tracker</div>
              <div style="font-size:13px;color:#e9f8f3">Smart, simple & delightful</div>
            </div>
          </div>
          <nav style="margin-top:12px">
            <a class="nav-btn" href="/"> <i class="fa-solid fa-house"></i> Home</a>
            <a class="nav-btn" href="/add"> <i class="fa-solid fa-plus"></i> Add Expense</a>
            <a class="nav-btn" href="/view"> <i class="fa-solid fa-table-list"></i> View Expenses</a>
            <a class="nav-btn" href="/summary"> <i class="fa-solid fa-chart-pie"></i> Summary</a>
            <a class="nav-btn" href="/charts"> <i class="fa-solid fa-chart-line"></i> Charts</a>
            <a class="nav-btn" href="/export_csv"> <i class="fa-solid fa-file-csv"></i> Export CSV</a>
            <a class="nav-btn" href="/budget"> <i class="fa-solid fa-wallet"></i> Budget</a>
            <a class="nav-btn" href="/recurring"> <i class="fa-solid fa-clock-rotate-left"></i> Recurring</a>
            <a class="nav-btn" href="/clear_all"> <i class="fa-solid fa-trash"></i> Clear All</a>
          </nav>
        </div>
      </header>

      <main class="container">
        {content}
      </main>

      <footer style="text-align:center;padding:18px;color:#6b7280">Made with ❤️ — single-file app</footer>
    </body>
    </html>
    """
    return render_template_string(template)

# ----------------- Routes -----------------
@app.route("/")
def home():
    # apply recurring items first
    apply_recurring()
    total_row = query("SELECT SUM(amount) AS total FROM expenses", one=True)
    total = round(total_row["total"],2) if total_row["total"] else 0
    # quick top 5 recent
    recent = query("SELECT * FROM expenses ORDER BY date DESC LIMIT 5")
    recent_rows = "".join(f"<div style='padding:8px 0;border-bottom:1px solid #f3f4f6'>{r['date']} — <b>{r['item']}</b> ₹{r['amount']}</div>" for r in recent)
    content = f"""
    <div class="grid">
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <div class="small">Total Spent</div>
            <div style="font-size:28px;font-weight:800">₹{total}</div>
            <div class="muted small">Last 5 expenses</div>
            <div style="margin-top:8px">{recent_rows or '<div class=\"muted\">No expenses yet</div>'}</div>
          </div>
          <div style="min-width:220px;text-align:center">
            <a href="/add" class="btn" style="width:160px">➕ Add Expense</a><br>
            <a href="/view" class="btn alt" style="width:160px;margin-top:10px">📋 View All</a>
          </div>
        </div>
      </div>
    </div>
    """
    return render_layout(content)

# Add expense (GET+POST)
@app.route("/add", methods=["GET","POST"])
def add():
    if request.method == "POST":
        item = request.form.get("item","").strip()
        try:
            amount = float(request.form.get("amount", "0") or 0)
        except:
            amount = 0
        date = request.form.get("date") or datetime.today().date().isoformat()
        category = request.form.get("category","Other").strip() or "Other"
        if not item:
            flash("Please enter an item name")
            return redirect(url_for("add"))
        query("INSERT INTO expenses (item, amount, date, category) VALUES (?,?,?,?)", (item, amount, date, category))
        flash("Expense added")
        return redirect(url_for("view"))
    # GET -> show form
    categories = sorted({r["category"] for r in query("SELECT DISTINCT category FROM expenses") if r["category"]})
    cat_opts = "".join(f"<option>{c}</option>" for c in categories)
    content = f"""
    <div class="card">
      <h2>Add Expense</h2>
      <form method="post" style="max-width:720px;margin-top:10px">
        <div class="row">
          <div style="flex:2">
            <label class="small">Item</label>
            <input name="item" placeholder="e.g. Coffee, Rent" required>
          </div>
          <div style="flex:1">
            <label class="small">Amount</label>
            <input name="amount" type="number" step="0.01" placeholder="e.g. 4.50" required>
          </div>
        </div>
        <div style="display:flex;gap:12px;margin-top:10px">
          <div style="flex:1">
            <label class="small">Date</label>
            <input name="date" type="date" value="{datetime.today().date().isoformat()}">
          </div>
          <div style="flex:1">
            <label class="small">Category</label>
            <select name="category">
              <option>Other</option>
              <option>Food</option>
              <option>Travel</option>
              <option>Shopping</option>
              <option>Bills</option>
              <option>Entertainment</option>
              {cat_opts}
            </select>
          </div>
        </div>
        <div style="margin-top:14px">
          <button class="btn">Save Expense</button>
          <a href="/" class="nav-btn" style="background:#fff;color:#111;margin-left:8px">Cancel</a>
        </div>
      </form>
    </div>
    """
    return render_layout(content, title="Add Expense")

# View + filters + search + sort
@app.route("/view")
def view():
    apply_recurring()
    q = request.args.get("q","").strip()
    cat = request.args.get("category","")
    from_date = request.args.get("from","")
    to_date = request.args.get("to","")
    sort = request.args.get("sort","date_desc")
    params = []
    where = "WHERE 1=1"
    if q:
        where += " AND item LIKE ?"
        params.append(f"%{q}%")
    if cat:
        where += " AND category = ?"
        params.append(cat)
    if from_date:
        where += " AND date >= ?"
        params.append(from_date)
    if to_date:
        where += " AND date <= ?"
        params.append(to_date)
    order = "ORDER BY date DESC"
    if sort == "date_asc": order = "ORDER BY date ASC"
    if sort == "amt_desc": order = "ORDER BY amount DESC"
    if sort == "amt_asc": order = "ORDER BY amount ASC"
    rows = query(f"SELECT * FROM expenses {where} {order}", tuple(params))
    total = sum(r["amount"] for r in rows) if rows else 0
    # categories for filter dropdown
    cats = [r["category"] for r in query("SELECT DISTINCT category FROM expenses") if r["category"]]
    cat_opts = "".join(f"<option value='{c}' {'selected' if c==cat else ''}>{c}</option>" for c in cats)
    # rows html
    rows_html = ""
    for r in rows:
        rows_html += f"<tr><td>{r['id']}</td><td>{r['item']}</td><td>₹{r['amount']}</td><td>{r['date']}</td><td>{r['category']}</td>" \
                     f"<td><a class='nav-btn' href='/edit/{r['id']}'>Edit</a> <a class='nav-btn' href='/delete/{r['id']}' style='background:#ff6b6b'>Delete</a></td></tr>"
    content = f"""
    <div class="card">
      <h2>View Expenses</h2>
      <div style="display:flex;gap:12px;align-items:center;margin-top:10px">
        <form style="display:flex;gap:8px" method="get">
          <input name="q" placeholder="Search item..." value="{q}">
          <select name="category"><option value=''>All Categories</option>{cat_opts}</select>
          <input name="from" type="date" value="{from_date}">
          <input name="to" type="date" value="{to_date}">
          <select name="sort">
            <option value="date_desc" {'selected' if sort=='date_desc' else ''}>Date ↓</option>
            <option value="date_asc" {'selected' if sort=='date_asc' else ''}>Date ↑</option>
            <option value="amt_desc" {'selected' if sort=='amt_desc' else ''}>Amount ↓</option>
            <option value="amt_asc" {'selected' if sort=='amt_asc' else ''}>Amount ↑</option>
          </select>
          <button class="btn">Apply</button>
        </form>
        <div style="margin-left:auto">
          <a class="nav-btn" href="/export_csv">Export CSV</a>
          <a class="nav-btn" href="/charts">Charts</a>
        </div>
      </div>

      <div style="margin-top:16px" class="stats">
        <div class="stat"><div class="small">Total</div><div style="font-weight:800">₹{round(total,2)}</div></div>
        <div class="stat"><div class="small">Highest</div><div style="font-weight:800">₹{round(max([r['amount'] for r in rows]) if rows else 0,2)}</div></div>
        <div class="stat"><div class="small">Lowest</div><div style="font-weight:800">₹{round(min([r['amount'] for r in rows]) if rows else 0,2)}</div></div>
        <div class="stat"><div class="small">Average</div><div style="font-weight:800">₹{round((sum([r['amount'] for r in rows]) / len(rows)) if rows else 0,2)}</div></div>
      </div>

      <table>
        <thead><tr><th>ID</th><th>Item</th><th>Amount</th><th>Date</th><th>Category</th><th>Action</th></tr></thead>
        <tbody>
          {rows_html or '<tr><td colspan=\"6\" class=\"muted\">No expenses found</td></tr>'}
        </tbody>
      </table>
    </div>
    """
    return render_layout(content, title="View Expenses")

# Edit
@app.route("/edit/<int:expense_id>", methods=["GET","POST"])
def edit(expense_id):
    if request.method == "POST":
        item = request.form.get("item","").strip()
        try:
            amount = float(request.form.get("amount","0") or 0)
        except:
            amount = 0
        date = request.form.get("date") or datetime.today().date().isoformat()
        category = request.form.get("category","Other")
        query("UPDATE expenses SET item=?, amount=?, date=?, category=? WHERE id=?", (item, amount, date, category, expense_id))
        flash("Updated")
        return redirect(url_for("view"))
    r = query("SELECT * FROM expenses WHERE id=?", (expense_id,), one=True)
    if not r:
        return render_layout("<h3 class='danger'>Not found</h3>")
    content = f"""
    <div class="card">
      <h2>Edit Expense</h2>
      <form method="post" style="max-width:720px">
        <label class="small">Item</label>
        <input name="item" value="{r['item']}" required>
        <label class="small">Amount</label>
        <input name="amount" type="number" step="0.01" value="{r['amount']}" required>
        <label class="small">Date</label>
        <input name="date" type="date" value="{r['date']}" required>
        <label class="small">Category</label>
        <input name="category" value="{r['category']}">
        <div style="margin-top:12px"><button class="btn">Save</button> <a class="nav-btn" href="/view">Cancel</a></div>
      </form>
    </div>
    """
    return render_layout(content, title="Edit Expense")

# Delete
@app.route("/delete/<int:expense_id>")
def delete(expense_id):
    query("DELETE FROM expenses WHERE id=?", (expense_id,))
    flash("Deleted")
    return redirect(url_for("view"))

# Summary (monthly summary + category breakdown)
@app.route("/summary")
def summary():
    apply_recurring()
    # monthly totals (YYYY-MM)
    rows = query("SELECT substr(date,1,7) AS month, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month DESC")
    months_html = "".join(f"<div style='padding:8px 0;border-bottom:1px solid #f3f4f6'>{r['month']}: ₹{round(r['total'],2)}</div>" for r in rows)
    # category sums
    cats = query("SELECT category, SUM(amount) as total FROM expenses GROUP BY category")
    cats_html = "".join(f"<div style='padding:6px 0'>{r['category'] or 'Uncategorized'}: <b>₹{round(r['total'],2)}</b></div>" for r in cats)
    content = f"""
    <div class="card">
      <h2>Summary</h2>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">{months_html or '<div class=\"muted\">No monthly data</div>'}</div>
        <div style="flex:1;min-width:260px">{cats_html or '<div class=\"muted\">No categories</div>'}</div>
      </div>
      <div style="margin-top:10px">
        <a class="nav-btn" href="/charts">View Charts</a>
      </div>
    </div>
    """
    return render_layout(content, title="Summary")

# Charts page — uses Chart.js; we pass data as JSON inlined
@app.route("/charts")
def charts():
    apply_recurring()
    cat_rows = query("SELECT category, SUM(amount) as total FROM expenses GROUP BY category")
    categories = [r['category'] or 'Uncategorized' for r in cat_rows]
    cat_totals = [round(r['total'],2) for r in cat_rows]
    month_rows = query("SELECT substr(date,1,7) AS month, SUM(amount) as total FROM expenses GROUP BY month ORDER BY month")
    months = [r['month'] for r in month_rows]
    month_totals = [round(r['total'],2) for r in month_rows]
    # budget
    budget_val = get_setting("budget")
    budget_val = float(budget_val) if budget_val else None
    total = query("SELECT SUM(amount) AS total FROM expenses", one=True)["total"] or 0
    progress = round(total / budget_val * 100,2) if budget_val and budget_val>0 else None
    content = f"""
    <div class="card">
      <h2>Charts</h2>
      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div style="flex:1;min-width:320px">
          <canvas id="pie"></canvas>
        </div>
        <div style="flex:1;min-width:320px">
          <canvas id="bar"></canvas>
        </div>
      </div>
      <div style="margin-top:14px">
        <div class="small">Budget: {('₹'+str(budget_val)) if budget_val else 'Not set'}</div>
        <div class="small">Total spent: ₹{round(total,2)}</div>
        {f"<div style='color:red;font-weight:700'>Over budget by ₹{round(total-budget_val,2)}</div>" if budget_val and total>budget_val else ''}
        {f"<div class='small'>Progress: {progress}%</div>" if progress is not None else ''}
      </div>
      <script>
        const categories = {json.dumps(categories)};
        const catTotals = {json.dumps(cat_totals)};
        const months = {json.dumps(months)};
        const monthTotals = {json.dumps(month_totals)};
        // Pie
        new Chart(document.getElementById('pie'), {{ type:'pie', data:{{ labels:categories, datasets:[{{ data:catTotals, backgroundColor:['#6C5CE7','#00B894','#FD9644','#FF6B6B','#00A8E8','#F6D55C'] }}] }}, options:{{responsive:true}} }});
        // Bar line
        new Chart(document.getElementById('bar'), {{ type:'bar', data:{{ labels:months, datasets:[{{ label:'Monthly total', data:monthTotals, backgroundColor:'#6C5CE7' }}] }}, options:{{responsive:true}} }});
      </script>
    </div>
    """
    return render_layout(content, title="Charts")

# Export CSV
@app.route("/export_csv")
def export_csv():
    rows = query("SELECT * FROM expenses ORDER BY date DESC")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Item","Amount","Date","Category"])
    for r in rows:
        writer.writerow([r["id"], r["item"], r["amount"], r["date"], r["category"]])
    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="expenses.csv")

# Budget set/view
@app.route("/budget", methods=["GET","POST"])
def budget():
    if request.method == "POST":
        try:
            val = float(request.form.get("budget") or 0)
        except:
            val = 0
        set_setting("budget", val)
        flash("Budget saved")
        return redirect(url_for("charts"))
    current = get_setting("budget")
    content = f"""
    <div class="card">
      <h2>Monthly Budget</h2>
      <form method="post" style="max-width:400px">
        <label class="small">Amount (₹)</label>
        <input name="budget" type="number" step="0.01" value="{current or ''}">
        <div style="margin-top:10px"><button class="btn">Save Budget</button> <a class="nav-btn" href="/charts">Cancel</a></div>
      </form>
    </div>
    """
    return render_layout(content, title="Budget")

# Clear all
@app.route("/clear_all")
def clear_all():
    query("DELETE FROM expenses")
    query("DELETE FROM recurring")
    flash("All data cleared")
    return redirect(url_for("home"))

# Recurring management
@app.route("/recurring", methods=["GET","POST"])
def recurring():
    if request.method == "POST":
        item = request.form.get("item","").strip()
        try:
            amount = float(request.form.get("amount","0") or 0)
        except:
            amount = 0
        start_date = request.form.get("start_date") or datetime.today().date().isoformat()
        freq = request.form.get("freq","monthly")
        category = request.form.get("category","Other")
        query("INSERT INTO recurring (item, amount, start_date, freq, category) VALUES (?,?,?,?,?)",
              (item, amount, start_date, freq, category))
        flash("Recurring saved")
        return redirect(url_for("recurring"))
    rows = query("SELECT * FROM recurring ORDER BY id DESC")
    rows_html = "".join(f"<div style='padding:8px;border-bottom:1px solid #f3f4f6'>{r['item']} ₹{r['amount']} every {r['freq']} starting {r['start_date']} <a class='nav-btn' href='/rec_remove/{r['id']}'>Remove</a></div>" for r in rows)
    content = f"""
    <div class="card">
      <h2>Recurring Expenses</h2>
      <form method="post" style="max-width:720px">
        <input name="item" placeholder="Item e.g. Rent" required>
        <input name="amount" type="number" step="0.01" placeholder="Amount" required>
        <input name="start_date" type="date" value="{datetime.today().date().isoformat()}">
        <select name="freq"><option value="monthly">Monthly</option></select>
        <input name="category" placeholder="Category">
        <div style="margin-top:10px"><button class="btn">Save Recurring</button></div>
      </form>
      <div style="margin-top:16px">{rows_html or '<div class=\"muted\">No recurring items</div>'}</div>
    </div>
    """
    return render_layout(content, title="Recurring")

@app.route("/rec_remove/<int:r_id>")
def rec_remove(r_id):
    query("DELETE FROM recurring WHERE id=?", (r_id,))
    flash("Recurring removed")
    return redirect(url_for("recurring"))

# ----------------- Start -----------------
if __name__ == "__main__":
    if not os.path.exists(DB):
        init_db()
    else:
        init_db()  # ensure schema
    app.run(debug=True)
