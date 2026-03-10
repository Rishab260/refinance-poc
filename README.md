# Refi-Ready POC

Serverless AWS proof-of-concept that builds a refinance-ready borrower audience from CSV data.

## What this project does

- Uploads borrower/loan/market/engagement CSV files to S3
- Creates and catalogs Glue tables for queryability
- Runs optional AWS Entity Resolution matching
- Uses Athena SQL to evaluate refinance eligibility
- Writes final audience CSV outputs to S3 and powers a local FastAPI dashboard

## Current run path (recommended)

### 1) Install dependencies

```bash
pip install -r requirements.txt
```

### 2) Configure AWS credentials

```bash
aws sts get-caller-identity
```

### 3) Run full orchestration

```bash
python run_poc.py
```

`run_poc.py` checks credentials/roles, runs infrastructure setup, then executes `scripts/run_pipeline.py`.

## Alternative: run steps manually

1. Create required IAM roles (see `iam-policies/CREATE_ROLES_INSTRUCTIONS.md`)
2. Setup infra:

```bash
python scripts/setup_infrastructure.py --glue-role-arn <YOUR_GLUE_ROLE_ARN>
```

3. Execute pipeline:

```bash
python scripts/run_pipeline.py
```

   The pipeline script now understands optional flags and SQL overrides
   (`--ltv-max`, `--spread-min`, `--qualification-query-file`, etc.).
   Use ``--athena-only`` when you only want the Athena step to execute and
   avoid re-uploading/crawling data.  These options are forwarded automatically
   when the dashboard triggers a run.

## Dashboard options

### Option A: FastAPI web dashboard (active)

```bash
bash launch_web_dashboard.sh
```

- URL: `http://127.0.0.1:8000`
- Reads latest pipeline CSV from `s3://refi-ready-poc-dev/output/athena/`
- Fallback path derives a dataset from `s3://refi-ready-poc-dev/raw/` if needed
- **Custom queries**: Frontend filters send requests to the new `/api/data` endpoint so you can programmatically retrieve records filtered by marketing category, LTV range and rate spread range. Example:

```bash
curl "http://127.0.0.1:8000/api/data?category=Hot+Lead&ltv_min=60&ltv_max=80"
```

  Additionally, the dashboard now offers a **Run Query Only** button (along
  with a new **Download CSV** control) located inside the filters panel.  The
  button submits the Athena eligibility query using the current filters
  without re‑running the full pipeline; logs and status appear in the live‑log
  box so you can watch progress.  A semi‑transparent loading overlay and
  “Loading…” placeholder values keep you from mistaking empty KPIs for real
  data.  Filters are debounced, so dragging slider controls or toggling options
  won’t immediately trigger a refresh until you pause.

  **Note:** simply changing the filter controls does *not* contact Athena at
  all – it only updates the subset of data already loaded into your browser.
  The “Run Query Only” action is required when you want the server to re‑run
  the Athena query and produce a fresh CSV based on the filter settings.

  Both the run/query and CSV download functions are backed by the
  `/api/athena/run` and `/api/athena/download` endpoints, making them easy to
  script.  When you click **Run Pipeline** the dashboard includes those same
  filters in the POST payload so the Athena query executed on the backend
  respects the user’s selections.  You can also trigger filtered runs manually
  with curl:

```bash
curl -X POST http://127.0.0.1:8000/api/pipeline/run \
     -H 'Content-Type: application/json' \
     -d '{"ltv_max":75, "spread_min":1.25, "category":["Hot Lead"]}'
```

  The same filter options can be submitted along with a pipeline run request
  (via POST to `/api/pipeline/run`) so that the Athena query executed on the
  backend respects the dashboard selections.  The dashboard's **Run Pipeline**
  button automatically wires this up.

  > **Tip**: moving the run/query controls into the filter section keeps
  > everything you need for ad‑hoc analysis in one place; the header now only
  > contains global actions (refresh, pipeline run).
This is useful for automation or sharing filter combinations.

#### View modes (new)

The dashboard now has a **View** dropdown in the header:

- **Refi Opportunity View**: shows refinance KPIs/charts and uses category + LTV + spread filters.
- **Account Health Status View**: shows account health KPIs/charts and hides LTV/spread filters.

Account Health metrics are displayed directly (not filtered by separate account-health checkboxes).
For **Mobile App Usage**, the UI treats a borrower as active if either:

- `mobile_app_logged_in` is true

The selected view is included in the shareable URL via `view_mode`.

### Option B: Static exported artifacts (already in repo)

- `refi_dashboard_export.html`
- `refi_borrowers_analyzed.csv`
- `refi_summary_by_category.csv`
- `refi_top_opportunities.csv`

### Option C: Amazon QuickSight

```bash
python scripts/setup_quicksight.py
```

See `QUICKSIGHT_SETUP.md`.

## Project structure

- `scripts/setup_infrastructure.py` - Creates S3/Glue resources
- `scripts/run_pipeline.py` - Uploads data, runs crawler + Entity Resolution + Athena
- `run_poc.py` - End-to-end orchestrator
- `app/main.py` - FastAPI dashboard app
- `data/` - Input CSV files

## Notes on older notebook docs

Some docs mention `refi_dashboard.ipynb`. That notebook file is not currently present in this repository; use the FastAPI dashboard or static HTML export above.

## Additional documentation

- `PIPELINE_ARCHITECTURE.md`
- `TECHNICAL_IMPLEMENTATION.md`
- `EXECUTIVE_SUMMARY.md`
- `QUICK_REFERENCE.md`
- `RUN_DASHBOARD.md`
