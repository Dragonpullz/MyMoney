# MyMoney Local Interface Plan (Flask)

> Goal: put a usable, browser-based interface on top of the existing
> `.banksync-analysis/` Python scripts so day-to-day spend / income / budget
> questions can be answered by clicking instead of typing CLI commands.
>
> **Runs on localhost only today**, but the architecture is chosen so the same
> codebase can later be hardened and exposed publicly with minimal rewrite.

## TL;DR — Method

**Use [Flask](https://flask.palletsprojects.com/).** Run it locally with:

```bash
flask --app mymoney run --host 127.0.0.1 --port 5000
# open http://127.0.0.1:5000
```

Why Flask was chosen (per repo owner's decision to treat this as "more real
world in case I eventually want to make it public"):

| Criterion | Why Flask fits the "could go public later" goal |
|---|---|
| Production-realistic | Same WSGI app runs locally under `flask run` and in prod under `gunicorn`/`uwsgi` behind nginx — no rewrite when going public. |
| Full control of HTML | Standard Jinja2 templates + plain HTML/CSS/JS. Anything from a single page to a multi-tenant SaaS uses the same template/blueprint shape. |
| Real auth path | Flask-Login + Flask-WTF (CSRF) are drop-in when the time comes. Streamlit/Gradio have no real auth story; Flask has the canonical one. |
| Real API path | Same blueprints can expose `/api/...` JSON endpoints for a future mobile / SPA client, plus a browser UI — no second framework. |
| Reuses existing code | Each route is a thin wrapper around the same functions in `banksync_analysis/core.py` and `banksync_analysis/commands.py` that the CLI scripts already use. |
| Charts | Chart.js (CDN, no build step) is plenty for cashflow / budget / projection charts and works the same locally and in prod. |
| Familiarity | Flask is the most widely understood Python web framework — easy to hand off, easy to find help, easy to read in 6 months. |

Alternatives considered:

- **FastAPI** — great if the API is the primary product. For a UI-first
  personal-finance app, Flask + Jinja is simpler and the perf delta does not
  matter at single-user scale. Revisit if a separate SPA frontend is added.
- **Django** — too heavy for a workspace this small (no ORM needs, no admin
  needs, no migrations needs — data lives in JSONL).
- **Streamlit / Gradio** — fastest to ship but the wrong shape for an
  eventual public deployment (no real auth, opinionated UI, server model is
  per-session not per-request). Explicitly ruled out by the repo owner.

## Constraints & Assumptions

1. **Localhost only today.** Bind to `127.0.0.1`. Add a config flag
   (`MYMONEY_BIND`, defaults to `127.0.0.1`) so future deployment can flip to
   `0.0.0.0` behind a reverse proxy without touching code.
2. **Read-only on the cache.** The web app only reads
   `.banksync-cache/normalized.jsonl` and `.banksync-cache/summary.json`. Data
   refresh still goes through the agent (MCP fetch) +
   `Import-BankSyncDump.py` + `Build-Summary.py`. The UI exposes a button that
   shells out to those scripts.
3. **No secrets in templates or JS.** The BankSync API key continues to live
   only in `.vscode/mcp.json`; the web app never sees it. `SECRET_KEY` for
   Flask sessions/CSRF is read from the environment (`MYMONEY_SECRET_KEY`),
   never committed.
4. **Reuse, don't rewrite.** Each route imports and calls the same
   `banksync_analysis.commands.*` functions the CLI scripts call. No business
   logic moves into the view layer.
5. **Production-ready shape from day one.** App factory (`create_app()`),
   blueprints, config classes (`DevConfig` / `ProdConfig`), env-driven
   settings, and a `wsgi.py` entry point — even though only `DevConfig` is
   used at first.
6. **Auth is stubbed but off.** A `requires_login` decorator exists and is a
   no-op in `DevConfig` (single local user). Flipping `MYMONEY_AUTH=on` later
   turns on Flask-Login + a single hashed-password user from env. Designed in,
   not bolted on.

## Proposed Layout

```
mymoney/
  __init__.py              # create_app() factory
  config.py                # DevConfig / ProdConfig
  extensions.py            # csrf = CSRFProtect(); login = LoginManager(); ...
  auth.py                  # requires_login decorator (no-op in dev)
  data.py                  # cached loaders for normalized.jsonl + summary.json
  blueprints/
    home.py                # GET /            -> dashboard / KPIs
    query.py               # GET /query       -> form + results (wraps query.py)
    cashflow.py            # GET /cashflow    -> wraps Get-MonthlyCashflow.py
    budgets.py             # GET /budgets     -> wraps Get-BudgetStatus.py
    subscriptions.py       # GET /subscriptions
    anomalies.py           # GET /anomalies
    opportunities.py       # GET /opportunities
    projection.py          # GET /projection
    report.py              # GET /report/<YYYY-MM> -> renders Build-MonthlyReport.py output
    refresh.py             # POST /refresh    -> CSRF-protected, kicks importer+summary
    api.py                 # GET /api/* JSON  -> reuses the same loader functions
  templates/
    base.html              # nav, flash messages, footer, Chart.js CDN
    home.html
    query.html
    ...
  static/
    css/app.css
    js/charts.js           # small helpers around Chart.js
wsgi.py                    # `app = create_app()`  for gunicorn
requirements.txt           # flask, flask-wtf, jinja2, pandas, python-dotenv
.flaskenv                  # FLASK_APP=mymoney, FLASK_DEBUG=1 (dev only, gitignored)
tests/
  test_smoke.py            # asserts each route returns 200 with empty cache
```

Notes:

- `create_app()` is the standard Flask app-factory pattern — required for both
  testability and clean prod deployment.
- Blueprints split each "page" into its own file; mirrors the existing
  one-script-per-task layout under `.banksync-analysis/`.
- `data.py` wraps the cache loaders with a small TTL + mtime-based cache so
  the home page is snappy without long-lived in-process state.
- Account picker defaults to **House Checking**, matching the repo
  convention. Read the default account ID from `rules.json`
  (`defaultAccountId`) at runtime — do not hard-code IDs in routes or
  templates.

## Route-by-Route Mapping

| Route | Backs onto | Form fields / query params |
|---|---|---|
| `GET /` | `summary.json` | none — KPIs for this month, last-refresh badge, refresh button |
| `GET /query` | `query.py` | `category` (preset or regex), `from`, `to`, `account_id`, `income`, `by_merchant`, `detailed` |
| `GET /cashflow` | `Get-MonthlyCashflow.py` | `months`, `account_id` |
| `GET /budgets` | `Get-BudgetStatus.py` + `budgets.json` | `month`, `account_id` |
| `GET /subscriptions` | `Find-Subscriptions.py` | `months_back`, `min_months`, `min_total` |
| `GET /anomalies` | `Find-Anomalies.py` | `window_months`, `outlier_sigma`, `min_new_merchant_amount` |
| `GET /opportunities` | `Find-Opportunities.py` | `lookback_months` |
| `GET /projection` | `Project-Spend.py` | `category`, `months_back`, `months_forward` |
| `GET /report/<YYYY-MM>` | `Build-MonthlyReport.py` | path param; renders existing Markdown report via `markdown` package |
| `POST /refresh` | `Import-BankSyncDump.py` + `Build-Summary.py` | file upload(s) of MCP dump JSON; CSRF token required |
| `GET /api/<resource>` | same loaders | JSON mirror of above for future SPA / mobile clients |

Every page also accepts `?format=json` and returns the same payload as the
HTML route — this is the "API path" without forking the code.

## Refresh Flow (manual, on-demand)

```
[ Refresh data ]  (POST /refresh, CSRF-protected)
  └─ Flask-WTF FileField(s) for MCP dump content.json(s)
       └─ each upload saved into a per-request tempdir via secure_filename()
       └─ subprocess.run([sys.executable, ".banksync-analysis/Import-BankSyncDump.py",
                          "-Files", *saved_paths], shell=False, check=True)
       └─ subprocess.run([sys.executable, ".banksync-analysis/Build-Summary.py"],
                          shell=False, check=True)
       └─ data.invalidate_cache()
       └─ flash("Refreshed N transactions"); redirect to /
```

Validation rules for uploads (must be in the route, not just docs):

- Reject any file whose `secure_filename()` result differs materially from the
  original name, or whose extension is not `.json`.
- Reject any payload over a sane size cap (e.g. `MAX_CONTENT_LENGTH = 32 MB`).
- Never pass user-controlled strings to a shell — always
  `subprocess.run([...], shell=False)` with a list of args.
- Resolve each saved path with `Path.resolve()` and assert it is inside the
  per-request tempdir before handing it to the importer (defense in depth
  against path traversal).

## Security / Privacy Notes (local today, deployable later)

Locked in now, even though we're localhost-only:

- Bind to `127.0.0.1` by default; the bind address is config, not code.
- `SECRET_KEY` from `MYMONEY_SECRET_KEY` env var; refuse to start with the
  default placeholder in `ProdConfig`.
- CSRF protection on every POST via Flask-WTF (`csrf.init_app(app)` in the
  factory). Yes, even on localhost — habits matter.
- `Content-Security-Policy` header set in `base.html`'s response (no inline
  scripts; Chart.js loaded from a pinned CDN with SRI, or vendored under
  `static/vendor/`).
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin` set via an `@app.after_request` hook.
- Cookies set with `Secure`, `HttpOnly`, `SameSite=Lax` in `ProdConfig`;
  `HttpOnly` + `SameSite=Lax` even in dev.
- Templates: rely on Jinja autoescape (on by default). Never use
  `|safe` on user/transaction data. The Markdown report is rendered with
  `markdown` + `bleach` allow-list, not raw HTML.
- File uploads: `MAX_CONTENT_LENGTH` set; allowed extensions enforced;
  `secure_filename()` applied; uploads saved into per-request tempdirs and
  deleted after processing.
- `subprocess.run([...], shell=False)` everywhere. Never `shell=True`.
- `.banksync-cache/` and `.flaskenv` are gitignored. The web app must never
  write outside `.banksync-cache/`.
- No telemetry, no external analytics, no external font CDNs.

Deferred until "go public" (designed for, not built yet):

- Flask-Login + a single hashed-password user (env-driven), enabled by
  `MYMONEY_AUTH=on`.
- TLS termination at a reverse proxy (nginx / Caddy); `ProxyFix` middleware
  enabled when `MYMONEY_BEHIND_PROXY=1`.
- Rate limiting (Flask-Limiter) on `/refresh` and `/api/*`.
- Structured request logging that scrubs amounts/merchants before logging.

## Testing

- `pytest` + Flask's `app.test_client()` smoke tests for every route (asserts
  200 with empty cache, 200 with a fixture cache).
- One CSRF test per POST route (rejects without token).
- One upload-validation test that rejects a non-`.json` upload.
- Pure functions (cache loaders, normalization) already live in
  `banksync_analysis/core.py` and have CLI scripts exercising them — the web
  layer adds tests for its own glue only.

## Implementation Checklist (incremental, ship-each-step)

- [ ] **Step 0 — Deps & skeleton.** `requirements.txt` (`flask`, `flask-wtf`,
      `markdown`, `bleach`, `python-dotenv`). `mymoney/__init__.py` with
      `create_app()`, `config.py`, `wsgi.py`, `.flaskenv` (gitignored).
- [ ] **Step 1 — Home + base template.** `GET /` reads `summary.json` and
      renders KPI cards. `base.html` with nav, flash, security headers, CSP.
- [ ] **Step 2 — Query route.** Highest-value page — replaces ~80% of CLI
      usage. Form with every flag `query.py` accepts; result table +
      by-month Chart.js bar chart. JSON mirror via `?format=json`.
- [ ] **Step 3 — Cashflow + Budgets routes.** Both fast (read `summary.json`).
- [ ] **Step 4 — Subscriptions, Anomalies, Opportunities, Projection
      routes.** Each one is a ~30-line wrapper around the corresponding
      `commands.py` function.
- [ ] **Step 5 — Monthly Report route.** Renders the existing
      `reports/<YYYY-MM>.md` via `markdown` + `bleach` allow-list. Button to
      regenerate.
- [ ] **Step 6 — Refresh flow.** `POST /refresh` with CSRF, file-upload
      validation, subprocess calls to importer + summary, cache invalidation,
      flash message.
- [ ] **Step 7 — Auth stub & polish.** `requires_login` no-op decorator on
      every route (so flipping `MYMONEY_AUTH=on` later "just works"). Account
      picker partial. Currency formatting filter. Pinned Chart.js with SRI.
- [ ] **Step 8 — Smoke tests.** `tests/test_smoke.py` covering every route +
      CSRF + upload validation.

## How to Run (once implemented)

Local development (single user, no auth):

```bash
pip install -r requirements.txt
export MYMONEY_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
flask --app mymoney run --host 127.0.0.1 --port 5000
# open http://127.0.0.1:5000
```

Production-shaped local run (closer to how a public deployment would look):

```bash
pip install gunicorn
MYMONEY_SECRET_KEY=... gunicorn -w 2 -b 127.0.0.1:5000 wsgi:app
```

## "If/When You Decide To Make It Public" Checklist

Not in scope for this PR, but the architecture supports flipping these on
without re-architecting:

- [ ] Set `MYMONEY_AUTH=on`, configure `MYMONEY_USER` + `MYMONEY_PASSWORD_HASH`.
- [ ] Switch config to `ProdConfig` (rejects default `SECRET_KEY`, sets
      `Secure` cookies).
- [ ] Put gunicorn behind nginx/Caddy with TLS; set `MYMONEY_BEHIND_PROXY=1`
      so `ProxyFix` is enabled.
- [ ] Enable Flask-Limiter on `/refresh` and `/api/*`.
- [ ] Add structured logging with PII scrubbing.
- [ ] Add a `Dockerfile` (multi-stage, non-root user) and a `docker-compose`
      file with a read-only bind mount for `.banksync-cache/`.
- [ ] Threat-model the upload + subprocess flow once more under the new
      trust boundary.

## Out of Scope (for this PR)

- Implementing the routes — this PR is the plan only.
- Multi-user / role-based access — single-user design even when public.
- Writing back to BankSync — read-only by design.
- Replacing the agent-driven MCP fetch — the web app defers to the existing
  agent + import scripts for data refresh.
