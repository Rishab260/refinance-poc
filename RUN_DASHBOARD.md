# Run the Refinance Dashboard

## Recommended dashboard: FastAPI web app

This repository’s active dashboard is the FastAPI app in `app/main.py`.

### Quick start

```bash
bash launch_web_dashboard.sh
```

Then open: `http://127.0.0.1:8000`

## What the dashboard uses

- Primary source: latest CSV in `s3://refi-ready-poc-dev/output/`
- Fallback source: derived dataset from `s3://refi-ready-poc-dev/raw/`
- Eligibility logic: `ltv_ratio <= 80` and `rate_spread >= 1.0`

## Run pipeline before opening dashboard (if needed)

```bash
python scripts/run_pipeline.py
```

The **Run Pipeline** button at the top of the dashboard will post the
current filter settings to the backend; the Athena query executed as part of
that run will incorporate the same constraints.

A new **Run Query Only** button allows you to execute the Athena
eligibility query directly (skipping upload, Glue, and entity resolution).
After it completes you can click the resulting "Download CSV" link to fetch
rows.

For end-to-end setup + execution:

```bash
python run_poc.py
```

## Troubleshooting

### Missing Python packages

```bash
pip install -r requirements.txt
```

### AWS credential issues

```bash
aws sts get-caller-identity
```

### No output data available

1. Run `python scripts/run_pipeline.py`
2. Verify CSVs exist under `s3://refi-ready-poc-dev/output/`

## Available static artifacts in this repo

- `refi_dashboard_export.html`
- `refi_borrowers_analyzed.csv`
- `refi_summary_by_category.csv`
- `refi_top_opportunities.csv`

## About `launch_dashboard.sh`

`launch_dashboard.sh` starts Jupyter and expects a `refi_dashboard.ipynb` notebook. That notebook is not currently present in this repository, so use `launch_web_dashboard.sh` unless you add your own notebook.
