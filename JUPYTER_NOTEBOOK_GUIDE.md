# Jupyter Notebook Guide (Optional / Legacy)

## Current repository status

This repository currently does **not** include `refi_dashboard.ipynb`.

- Recommended dashboard path: `bash launch_web_dashboard.sh`
- Alternative artifact path: open `refi_dashboard_export.html`

Use this guide only if you want to create your own notebook for ad-hoc analysis.

## If you want to work in Jupyter anyway

### 1) Install Jupyter

```bash
pip install jupyter notebook
```

### 2) Launch Jupyter in this repo

```bash
cd /home/rishabsaini261/codersbrain/refinance-poc
jupyter notebook
```

### 3) Create a new notebook and load pipeline outputs

Use S3 output first:

```python
import pandas as pd

df = pd.read_csv("s3://refi-ready-poc-dev/output/<latest_output_file>.csv")
df.head()
```

Or use local exported CSV files already in this repository:

```python
import pandas as pd

df = pd.read_csv("refi_borrowers_analyzed.csv")
df.head()
```

## Suggested notebook sections

1. Data load and schema checks
2. Eligibility metrics (`ltv_ratio`, `rate_spread`)
3. Marketing category distribution
4. Top savings opportunities
5. Export to CSV/HTML

## Minimal package set

```bash
pip install pandas plotly boto3 s3fs
```

## Troubleshooting

### S3 read fails

- Verify credentials: `aws sts get-caller-identity`
- Verify object exists under `s3://refi-ready-poc-dev/output/`

### Missing modules

```bash
pip install -r requirements.txt
```

## Related docs

- `README.md`
- `RUN_DASHBOARD.md`
- `TECHNICAL_IMPLEMENTATION.md`
- `PIPELINE_ARCHITECTURE.md`
