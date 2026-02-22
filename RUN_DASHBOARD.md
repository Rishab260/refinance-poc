# 📊 Run the Refinance Dashboard

## ✅ Prerequisites - Already Setup!
- ✓ s3fs installed  
- ✓ pandas, plotly, numpy installed
- ✓ AWS credentials configured
- ✓ Data loaded in S3

## 🚀 Quick Start

### Option 1: Use the Launch Script (Easiest)
```bash
bash launch_dashboard.sh
```

### Option 2: Manual Launch
```bash
jupyter notebook refi_dashboard.ipynb
```

## 📈 What to Expect

The dashboard will analyze **10 refinance-eligible borrowers** out of 51 total borrowers in the system.

### Key Metrics:
- **Total Borrowers Analyzed:** 51
- **Refinance-Eligible:** 10 borrowers
- **Criteria:** LTV ≤ 80% AND rate spread ≥ 1.0%
- **Data Source:** S3 bucket `s3://refi-ready-poc-dev/raw/`

### Sample Opportunities:
| Borrower | Current Rate | Market Rate | Monthly Savings |
|----------|--------------|-------------|-----------------|
| John Smith | 4.5% | 3.2% | $250 |
| Jane Doe | 3.8% | 2.5% | $200 |
| Mary Johnson | 4.9% | 3.5% | $150 |

## 📋 Dashboard Sections
1. **Executive Summary** - KPIs and key metrics
2. **Marketing Categories** - Borrower segmentation (Immediate Action, Hot Lead, etc.)
3. **Rate Analysis** - Interest rate spread distribution
4. **Savings Opportunities** - Monthly/annual savings potential
5. **Geographic Distribution** - Map visualization
6. **Portfolio Overview** - Borrower characteristics
7. **Engagement Analysis** - Digital channel usage
8. **Property Analysis** - Home values and equity
9. **Loan Portfolio** - Loan types and amounts
10. **Top Opportunities** - Best refinance candidates
11. **Credit Analysis** - Credit score distribution
12. **Equity Distribution** - Home equity analysis
13. **Rate Spread Analysis** - Detailed rate comparison
14. **Contact Priority** - Who to contact first
15. **Export Results** - Download CSV and HTML files

## 🎯 Running Specific Cells

The notebook has **32 cells** organized into **15 sections**:
- **Cells 1-3:** Setup and installation
- **Cells 4-11:** Data loading and preparation
- **Cells 12-31:** Visualizations and analysis
- **Cell 32:** Export results

### To Run All Cells:
1. Click **Cell** → **Run All** in the Jupyter menu

### To Run Step-by-Step:
1. Press **Shift + Enter** to run each cell sequentially
2. Watch output appear below each cell

## 📥 Output Files
After running all cells, you'll get:
- `refi_dashboard_export.html` - Complete interactive dashboard
- `refi_borrowers_analyzed.csv` - All 10 eligible borrowers
- `refi_top_opportunities.csv` - Top 5 opportunities

## 🔧 Troubleshooting

### If you see "No module named 's3fs'":
```bash
pip install s3fs
```

### If data shows 0 rows:
✓ Already fixed! The notebook now reads directly from S3 CSVs, bypassing Athena.

### If AWS credentials error:
```bash
aws configure
```

## 🎨 Customization

### Change Eligibility Criteria:
Edit **Cell 9** to adjust filters:
```python
df = df[
    (df['ltv_ratio'] <= 80) &  # Change this threshold
    ((df['current_interest_rate'] - df['market_rate_offer']) >= 1.0)  # Or this
].copy()
```

### Change Marketing Categories:
Edit **Cell 11** function `categorize_borrower()`:
```python
def categorize_borrower(rate_spread):
    if rate_spread > 1.25:
        return 'Immediate Action'
    # Adjust thresholds here
```

## 📊 Data Sources
- **Borrower Info:** `s3://refi-ready-poc-dev/raw/borrower_information.csv`
- **Loan Info:** `s3://refi-ready-poc-dev/raw/loan_information.csv`
- **Market Data:** `s3://refi-ready-poc-dev/raw/market_equity.csv`
- **Engagement:** `s3://refi-ready-poc-dev/raw/borrower_engagement.csv`

## ✅ Status: READY TO USE!
All dependencies installed, all configuration complete. Just run the notebook!
