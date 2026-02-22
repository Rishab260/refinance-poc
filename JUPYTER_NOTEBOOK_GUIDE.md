# Jupyter Notebook Dashboard - Quick Start Guide

## 🚀 Getting Started

### Step 1: Install Jupyter
```bash
# Using conda (recommended)
conda install jupyter notebook

# Or using pip
pip install jupyter notebook
```

### Step 2: Launch Jupyter Notebook
```bash
cd /home/rishabsaini261/codersbrain/refinance-poc
jupyter notebook
```

This will open Jupyter in your browser at `http://localhost:8888`

### Step 3: Open the Dashboard
1. In the Jupyter file browser, click on `refi_dashboard.ipynb`
2. Run all cells: **Cell** → **Run All** (or **Shift + Enter** for each cell)

---

## 📊 What's in the Notebook

### 15 Comprehensive Sections:

1. **Setup & Installation** - Install required packages (boto3, pandas, plotly, pyathena)
2. **Import Libraries** - Load all visualization libraries
3. **Configure AWS Athena** - Connect to your data pipeline
4. **Load Data** - Query the unified_refi_dataset view
5. **Data Preparation** - Calculate rate spread, marketing categories, engagement scores
6. **Executive KPIs** - Total borrowers, savings, rate spread, LTV metrics
7. **Marketing Categories** - Distribution across urgency tiers
8. **Rate Comparison** - Scatter plot showing current vs market rates
9. **Top Opportunities** - Top 10 borrowers by savings potential
10. **LTV Heatmap** - Distribution heatmap for targeting
11. **Engagement Metrics** - Digital channel adoption (pie charts)
12. **Engagement Score** - Overall digital engagement distribution
13. **Summary Statistics** - Comprehensive data overview
14. **Export Dashboard** - Save as standalone HTML file
15. **Data Export** - Export processed CSV files

---

## 💡 Key Features

### ✅ **FREE** - No AWS QuickSight costs!
- Uses free Python libraries (pandas, plotly)
- Only pay for Athena queries (~$0.000005 per query)

### 📈 **Interactive Visualizations**
- Hover for details
- Zoom and pan
- Click legends to filter
- Professional Plotly charts

### 📤 **Multiple Export Options**
- **HTML Dashboard** - Share via email or web
- **CSV Files** - Import to Excel, Tableau, etc.
- **Summary Reports** - By marketing category
- **Top Opportunities** - Priority call lists

### 🔄 **Real-Time Data**
- Queries Athena directly
- Always shows latest pipeline results
- No data staleness issues

---

## 🎯 Usage Scenarios

### For Marketing Teams
```python
# Filter for immediate action borrowers
immediate = df[df['marketing_category'] == 'Immediate Action']
immediate[['full_name', 'monthly_savings_est', 'engagement_score']].to_csv('immediate_action_list.csv')
```

### For Executives
- View KPI section (Cell 6) for quick overview
- Check summary statistics (Cell 13) for detailed metrics
- Export HTML dashboard for presentations

### For Data Analysts
- Modify queries to add filters
- Adjust marketing category thresholds
- Create custom visualizations

---

## 📦 Required Packages

The notebook will auto-install these packages:
- `boto3` - AWS SDK
- `pandas` - Data manipulation
- `plotly` - Interactive visualizations
- `pyathena` - Athena SQL connector
- `numpy` - Numerical operations

---

## 🔧 Troubleshooting

### Issue: "ModuleNotFoundError"
**Solution**: Run the first code cell to install packages
```python
!pip install boto3 pandas plotly pyathena numpy -q
```

### Issue: "Connection to Athena failed"
**Solution**: Check AWS credentials
```bash
aws configure list
aws sts get-caller-identity
```

### Issue: "Table 'unified_refi_dataset' not found"
**Solution**: Run the pipeline first
```bash
python scripts/run_pipeline.py
```

### Issue: "No data returned from query"
**Solution**: Verify data exists in Athena
```sql
SELECT COUNT(*) FROM refi_ready_db.unified_refi_dataset;
```

---

## 🎨 Customization Tips

### Change Color Scheme
```python
# Modify color_map in Cell 7
color_map = {
    'Immediate Action': '#YOUR_COLOR',
    'Hot Lead': '#YOUR_COLOR',
    'Watchlist': '#YOUR_COLOR',
    'Ineligible': '#YOUR_COLOR'
}
```

### Adjust Marketing Categories
```python
# Modify categorize_borrower function in Cell 5
def categorize_borrower(rate_spread):
    if rate_spread > 1.5:  # Change threshold
        return 'Immediate Action'
    # ... add more conditions
```

### Add New Visualizations
```python
# Example: Savings by LTV range
fig = px.box(df, x='ltv_bin', y='monthly_savings_est', title='Savings Distribution by LTV')
fig.show()
```

---

## 📊 Output Files

After running the notebook, you'll get:

1. **refi_dashboard_export.html** - Interactive HTML dashboard
2. **refi_borrowers_analyzed.csv** - Full dataset with calculated fields
3. **refi_summary_by_category.csv** - Aggregated statistics
4. **refi_top_opportunities.csv** - Top 20 savings opportunities

---

## 🚀 Advanced Usage

### Schedule Automatic Updates
```bash
# Create a cron job to run daily at 6 AM
0 6 * * * cd /home/rishabsaini261/codersbrain/refinance-poc && jupyter nbconvert --execute refi_dashboard.ipynb --to html
```

### Convert to Python Script
```bash
jupyter nbconvert --to script refi_dashboard.ipynb
# Creates refi_dashboard.py
```

### Run Headless (No Browser)
```bash
jupyter nbconvert --execute refi_dashboard.ipynb --to html
# Generates refi_dashboard.html
```

---

## 📞 Support

### For Notebook Issues:
- Jupyter Documentation: https://jupyter.org/documentation
- Plotly Documentation: https://plotly.com/python/

### For POC/Pipeline Issues:
- Check [README.md](README.md)
- Review [TECHNICAL_IMPLEMENTATION.md](TECHNICAL_IMPLEMENTATION.md)
- Run: `python scripts/run_pipeline.py`

---

## 🎉 Advantages Over QuickSight

| Feature | Jupyter Notebook | QuickSight |
|---------|-----------------|------------|
| **Cost** | FREE (except Athena queries) | ~$19/month |
| **Customization** | Full Python control | Limited to UI options |
| **Data Access** | Direct Athena queries | Requires data source setup |
| **Sharing** | Export HTML, Email, Git | Requires QuickSight subscription |
| **Offline Access** | Work locally | Requires AWS connection |
| **Version Control** | Git-friendly | Dashboard versioning limited |
| **Learning Curve** | Python knowledge needed | Point-and-click interface |

---

## ✨ Quick Win

**Want a dashboard in 2 minutes?**

1. Open terminal: `jupyter notebook`
2. Click `refi_dashboard.ipynb`
3. Click **Cell** → **Run All**
4. Scroll through beautiful visualizations!
5. Find `refi_dashboard_export.html` - send to your team!

**That's it! 🎊**

---

## Next Steps

- [x] Create Jupyter notebook ✅
- [ ] Run the notebook and explore data
- [ ] Customize visualizations to your needs
- [ ] Export and share HTML dashboard
- [ ] Set up automated daily reports
- [ ] Integrate with other data sources

---

**Happy Analyzing! 📊✨**
