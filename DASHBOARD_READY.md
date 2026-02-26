# Dashboard Status

## Current state

Dashboard support in this repository is active and working via FastAPI.

- Primary launch command: `bash launch_web_dashboard.sh`
- URL: `http://127.0.0.1:8000`
- Data source: latest CSV from `s3://refi-ready-poc-dev/output/`
- Fallback source: derived dataset from `s3://refi-ready-poc-dev/raw/`

## Recommended run sequence

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Execute the pipeline (if output is missing/stale):

```bash
python scripts/run_pipeline.py
```

3. Launch dashboard:

```bash
bash launch_web_dashboard.sh
```

## Local artifacts available now

- `refi_dashboard_export.html`
- `refi_borrowers_analyzed.csv`
- `refi_summary_by_category.csv`
- `refi_top_opportunities.csv`

## Important note on notebook workflow

`launch_dashboard.sh` expects `refi_dashboard.ipynb`, which is not currently present in this repository. Use the FastAPI launcher unless you add your own notebook.

## Related docs

- [README.md](README.md)
- [RUN_DASHBOARD.md](RUN_DASHBOARD.md)
- [JUPYTER_NOTEBOOK_GUIDE.md](JUPYTER_NOTEBOOK_GUIDE.md)
