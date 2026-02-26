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

## Dashboard options

### Option A: FastAPI web dashboard (active)

```bash
bash launch_web_dashboard.sh
```

- URL: `http://127.0.0.1:8000`
- Reads latest pipeline CSV from `s3://refi-ready-poc-dev/output/`
- Fallback path derives a dataset from `s3://refi-ready-poc-dev/raw/` if needed

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
