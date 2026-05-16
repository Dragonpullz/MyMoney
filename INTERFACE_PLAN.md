# MyMoney Local Interface Plan

> Goal: put a usable, browser-based interface on top of the existing
> `.banksync-analysis/` Python scripts so day-to-day spend / income / budget
> questions can be answered by clicking instead of typing CLI commands.
> Localhost only, single user (Tim).

## TL;DR — Recommended Method

**Use [Streamlit](https://streamlit.io/).** Run it locally with:

```bash
streamlit run app/Home.py --server.address 127.0.0.1 --server.port 8501
```

Why Streamlit (vs Flask / FastAPI / Dash / Gradio / Jupyter):

| Criterion | Why Streamlit wins here |
|---|---|
| Language fit | Repo is 100% Python; Streamlit is pure Python — no JS, no HTML, no templating. |
| Reuses existing code | Every script in `.banksync-analysis/` already exposes a `main()` / functions over `banksync_analysis.core` and `commands`. Streamlit pages can `import` them directly and render the returned dicts/DataFrames. |
| Charts & tables | Built-in `st.dataframe`, `st.bar_chart`, `st.line_chart`, plus first-class Plotly/Altair if needed for the Mermaid-style charts in `Build-MonthlyReport.py`. |
| Filters/widgets | `st.date_input`, `st.selectbox` (accounts), `st.multiselect` (categories), `st.text_input` (regex) cover every flag `query.py` accepts. |
| Multi-page | `app/pages/*.py` auto-creates a left-nav — one page per existing script. |
| Localhost-only | `--server.address 127.0.0.1` binds to loopback; no auth needed for single-user local use. |
| Effort | Minimum viable UI is ~1 file (~50 lines) wrapping `query.py`. Full dashboard is a long afternoon. |

Rejected alternatives:

- **Flask / FastAPI + Jinja/React** — flexible but requires templating, a
  frontend toolchain, and hand-rolled charting. Overkill for a personal
  single-user tool.
- **Dash** — viable, but more boilerplate (callbacks, layouts) than Streamlit
  for the same dashboards.
- **Gradio** — great for ML demos, weaker for multi-page dashboards with
  tables, filters, and drill-down.
- **Jupyter / Voila** — works, but feels like notebooks instead of an app; no
  real navigation or persistent state.
- **Pure CLI + HTML report files** (current `Build-MonthlyReport.py`) — fine
  for monthly digest, bad for ad-hoc "how much on gas last 3 months" clicks.

## Constraints & Assumptions

1. **Localhost only.** Bind to `127.0.0.1`; do not expose to the LAN.
   No auth layer required because the OS user boundary is the trust boundary.
2. **Read-only on the cache.** The UI only reads
   `.banksync-cache/normalized.jsonl` and `.banksync-cache/summary.json`.
   Refreshing data still goes through the agent (MCP fetch) +
   `Import-BankSyncDump.py` + `Build-Summary.py` — the UI just surfaces a
   "Last refreshed: …" badge and a button that shells out to those scripts.
3. **No secrets in the app.** BankSync API key continues to live only in
   `.vscode/mcp.json`; the UI never sees it.
4. **No new heavyweight deps.** Streamlit + pandas (already a transitive of
   most analysis libs) + optional Altair/Plotly. That's it.
5. **Reuse, don't rewrite.** Each page is a thin wrapper around an existing
   script's underlying function. No business logic moves into the UI layer.

## Proposed Layout

```
app/
  Home.py                 # landing: last-refresh, headline KPIs, refresh button
  pages/
    1_Cashflow.py         # wraps Get-MonthlyCashflow.py
    2_Query.py            # wraps query.py (the workhorse page)
    3_Budgets.py          # wraps Get-BudgetStatus.py
    4_Subscriptions.py    # wraps Find-Subscriptions.py
    5_Anomalies.py        # wraps Find-Anomalies.py
    6_Opportunities.py    # wraps Find-Opportunities.py
    7_Projection.py       # wraps Project-Spend.py
    8_Monthly_Report.py   # renders Build-MonthlyReport.py output inline
  _shared.py              # cached loaders for normalized.jsonl + summary.json
requirements.txt          # streamlit, pandas, altair (optional)
.streamlit/
  config.toml             # headless=true, address=127.0.0.1, theme
```

Notes:

- Streamlit auto-generates the sidebar nav from `pages/` filenames; the
  numeric prefix controls order.
- `_shared.py` uses `@st.cache_data` keyed on the cache file mtimes so reloads
  are instant but auto-invalidate after a refresh.
- Account picker defaults to **House Checking** (`P45rzOvVJ7uA59M1o3REU5gvZvmzQ7Igk6yM9`)
  on every page, matching the repo convention in
  `.github/copilot-instructions.md` and `rules.json`.

## Page-by-Page Mapping

| Page | Backs onto | Widgets |
|---|---|---|
| Home | `summary.json` | KPI row (this month spend / income / net), last-refresh, "Refresh data" button |
| Cashflow | `Get-MonthlyCashflow.py` | months slider, account select, line + bar chart, table |
| Query | `query.py` | category preset/regex, date range, account, income toggle, by-merchant toggle, detail toggle, results table + by-month chart |
| Budgets | `Get-BudgetStatus.py` + `budgets.json` | month picker, account select, progress bars per virtual category |
| Subscriptions | `Find-Subscriptions.py` | months-back slider, min-months / min-total, sortable table, "annualized cost" total |
| Anomalies | `Find-Anomalies.py` | window slider, sigma slider, per-bucket sections (outliers, dupes, fees, new-merchant) |
| Opportunities | `Find-Opportunities.py` | lookback slider, ranked table with estimated monthly impact |
| Projection | `Project-Spend.py` | category select (presets + Spend/Income/Net), months-back / months-forward, ensemble line chart with ±2σ band |
| Monthly Report | `Build-MonthlyReport.py` | month picker → renders the existing Markdown report inline via `st.markdown` |

## Refresh Flow (manual, on-demand)

The agent still owns the MCP fetch. The UI exposes a button that shells out to
the existing local steps once dump JSON paths are pasted/selected:

```
[ Refresh data ]
  └─ st.file_uploader for MCP dump content.json(s)
       └─ subprocess: python3 .banksync-analysis/Import-BankSyncDump.py -Files ...
       └─ subprocess: python3 .banksync-analysis/Build-Summary.py
       └─ st.cache_data.clear() and st.rerun()
```

No background daemon, no scheduler — explicit and auditable.

## Security / Privacy Notes

- Bind to `127.0.0.1` only. Add a `.streamlit/config.toml` with
  `server.address = "127.0.0.1"` and `server.headless = true`.
- Do **not** add `server.enableCORS = false` / `server.enableXsrfProtection = false`.
  Keep Streamlit defaults.
- No telemetry: set `browser.gatherUsageStats = false`.
- `.banksync-cache/` is already gitignored; the UI must never write outside it.
- Never log raw transaction text to anything other than the local browser
  session.

## Implementation Checklist (incremental, ship-each-step)

- [ ] **Step 0 — Add deps.** `requirements.txt` with `streamlit`, `pandas`.
      Optionally `altair` for prettier charts.
- [ ] **Step 1 — Skeleton.** `app/Home.py` that reads `summary.json` and shows
      headline KPIs + a "Last refreshed" timestamp. `.streamlit/config.toml`
      locked to `127.0.0.1`.
- [ ] **Step 2 — Query page.** Port every `query.py` flag to widgets. This is
      the highest-value page and replaces 80% of CLI usage.
- [ ] **Step 3 — Cashflow + Budgets pages.** Both read `summary.json`, fast.
- [ ] **Step 4 — Subscriptions, Anomalies, Opportunities, Projection pages.**
      Each one is a ~30-line wrapper around the corresponding script's
      function returning a dict/table.
- [ ] **Step 5 — Monthly Report page.** Render `reports/<YYYY-MM>.md` inline;
      add a button that regenerates it for the selected month.
- [ ] **Step 6 — Refresh flow.** File uploader + subprocess calls to
      `Import-BankSyncDump.py` and `Build-Summary.py`, then
      `st.cache_data.clear()`.
- [ ] **Step 7 — Polish.** Consistent account picker via `_shared.py`,
      formatted currency, sortable tables, dark theme in `config.toml`.

## How to Run (once implemented)

```bash
pip install -r requirements.txt
streamlit run app/Home.py
# open http://127.0.0.1:8501
```

Stop with Ctrl+C. No service, no daemon, no port forwarding.

## Out of Scope (intentionally)

- Multi-user / auth / TLS — not needed for a single-user local tool.
- Hosting on a server / Docker / cloud — explicitly localhost only.
- Writing back to BankSync — read-only by design.
- Replacing the agent-driven MCP fetch — the UI defers to the existing
  agent + import scripts for data refresh.
