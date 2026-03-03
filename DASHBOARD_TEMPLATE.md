# QuickSight Dashboard Template: Refi-Ready Borrowers

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      REFI-READY BORROWER DASHBOARD                          │
│                           Refinance POC 2026                                │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────┬──────────────┬──────────────┬──────────────┐
│   KPI TILE   │   KPI TILE   │   KPI TILE   │   KPI TILE   │
│              │              │              │              │
│   Total      │   Total      │   Average    │   Average    │
│ Borrowers    │  Savings     │   Rate       │     LTV      │
│              │              │   Spread     │    Ratio     │
│    ###       │   $###K      │   ##.##%     │   ##.##%     │
└──────────────┴──────────────┴──────────────┴──────────────┘

┌────────────────────────────────────────┬──────────────────────────────────┐
│                                        │                                  │
│   BORROWERS BY MARKETING CATEGORY      │   RATE COMPARISON ANALYSIS       │
│                                        │                                  │
│   [BAR CHART - Vertical]               │   [SCATTER PLOT]                 │
│                                        │                                  │
│   Immediate Action  ████████           │   Current Rate vs Market Rate    │
│   Hot Lead          ████████████       │   Size = Monthly Savings         │
│   Watchlist         ████████           │   Color = Category               │
│                                        │                                  │
└────────────────────────────────────────┴──────────────────────────────────┘

┌────────────────────────────────────────┬──────────────────────────────────┐
│                                        │                                  │
│   TOP SAVINGS OPPORTUNITIES            │   LTV VS RATE SPREAD HEATMAP     │
│                                        │                                  │
│   [HORIZONTAL BAR CHART]               │   [HEAT MAP]                     │
│                                        │                                  │
│   John Doe    █████████████ $450      │        0-0.5% 0.5-1% 1-1.5% >1.5%│
│   Jane Smith  ██████████ $400         │   0-60%   █      █      ██    ██ │
│   Bob Wilson  ████████ $350           │  60-70%   █      ██     ██    █  │
│   ...                                  │  70-80%   ██     ██     █     █  │
│                                        │   >80%    █      █      █     █  │
└────────────────────────────────────────┴──────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│                       ENGAGEMENT METRICS                                    │
│                                                                             │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐               │
│  │ Paperless   │   Email     │  Mobile App │     SMS     │               │
│  │  Billing    │ Engagement  │   Usage     │   Opt-In    │               │
│  │             │             │             │             │               │
│  │ [DONUT]     │ [DONUT]     │ [DONUT]     │ [DONUT]     │               │
│  │  Yes: 65%   │  Yes: 42%   │  Yes: 38%   │  Yes: 55%   │               │
│  │  No: 35%    │  No: 58%    │  No: 62%    │  No: 45%    │               │
│  └─────────────┴─────────────┴─────────────┴─────────────┘               │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│                          FILTERS (Always Visible)                           │
│                                                                             │
│  Marketing Category: [dropdown]  LTV Ratio: [slider]  Rate Spread: [slider]│
│  Engagement: [☐ Email ☐ Mobile App ☐ Paperless ☐ SMS]                     │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Visual Specifications

### Row 1: KPI Tiles (4 tiles)

#### Tile 1: Total Refi-Ready Borrowers
- **Type**: KPI
- **Value**: `COUNT(borrower_id)`
- **Format**: Number (#,##0)
- **Background**: Light blue gradient
- **Icon**: 👥

#### Tile 2: Total Monthly Savings Potential
- **Type**: KPI
- **Value**: `SUM(monthly_savings_est)`
- **Format**: Currency ($#,##0)
- **Background**: Green gradient
- **Icon**: 💰
- **Comparison**: Show YoY change if available

#### Tile 3: Average Rate Spread
- **Type**: KPI
- **Value**: `AVG(rate_spread)`
- **Calculated Field**: `{current_interest_rate} - {market_rate_offer}`
- **Format**: Percentage (#.##%)
- **Background**: Orange gradient
- **Icon**: 📊

#### Tile 4: Average LTV Ratio
- **Type**: KPI
- **Value**: `AVG(ltv_ratio)`
- **Format**: Percentage (#.##%)
- **Background**: Purple gradient
- **Icon**: 🏠

---

### Row 2: Primary Analysis Charts

#### Left: Borrowers by Marketing Category
- **Type**: Vertical bar chart
- **X-axis**: Marketing Category (Calculated field)
- **Y-axis**: Count of borrower_id
- **Colors**: 
  - Immediate Action: #E74C3C (Red)
  - Hot Lead: #F39C12 (Orange)
  - Watchlist: #F1C40F (Yellow)
  - Ineligible: #95A5A6 (Gray)
- **Sort**: Descending by count
- **Data Labels**: Show count on bars
- **Title**: "Borrowers by Marketing Category"

#### Right: Rate Comparison Analysis
- **Type**: Scatter plot
- **X-axis**: current_interest_rate (2.0% to 7.0%)
- **Y-axis**: market_rate_offer (2.0% to 5.0%)
- **Bubble Size**: monthly_savings_est
- **Color**: Marketing Category
- **Trend Line**: Yes (diagonal for reference)
- **Grid**: Major gridlines only
- **Title**: "Rate Comparison Analysis"
- **Insight**: Points above trend line have higher savings potential

---

### Row 3: Detailed Analysis

#### Left: Top Savings Opportunities
- **Type**: Horizontal bar chart
- **Y-axis**: full_name (Top 10)
- **Calculated Field**: `concat({first_name}, ' ', {last_name})`
- **X-axis**: monthly_savings_est
- **Sort**: Descending by savings
- **Format**: Currency ($#,##0)
- **Color**: Gradient from light to dark blue
- **Data Labels**: Show dollar amount
- **Title**: "Top 10 Savings Opportunities"

#### Right: LTV vs Rate Spread Heatmap
- **Type**: Heat map
- **Rows**: LTV Category (binned)
  - 0-60%: Low Risk
  - 60-70%: Medium Risk
  - 70-80%: High Risk
  - >80%: Ineligible
- **Columns**: Rate Spread (binned)
  - 0-0.5%: Minimal
  - 0.5-1.0%: Moderate
  - 1.0-1.5%: Strong
  - >1.5%: Excellent
- **Values**: COUNT(borrower_id)
- **Color Scheme**: Blue (low) to Red (high)
- **Title**: "LTV vs Rate Spread Distribution"

---

### Row 4: Engagement Metrics (4 donut charts)

#### Chart 1: Paperless Billing
- **Type**: Donut chart
- **Group**: paperless_billing
- **Value**: COUNT(borrower_id)
- **Colors**: Green (Yes), Gray (No)
- **Center Label**: Percentage enrolled
- **Title**: "Paperless Billing Adoption"

#### Chart 2: Email Engagement
- **Type**: Donut chart
- **Group**: email_open_last_30d
- **Value**: COUNT(borrower_id)
- **Colors**: Blue (Yes), Gray (No)
- **Center Label**: Percentage active
- **Title**: "Email Opens (Last 30 Days)"

#### Chart 3: Mobile App Usage
- **Type**: Donut chart
- **Group**: mobile_app_login_last_30d
- **Value**: COUNT(borrower_id)
- **Colors**: Purple (Yes), Gray (No)
- **Center Label**: Percentage active
- **Title**: "Mobile App Logins (Last 30 Days)"

#### Chart 4: SMS Opt-In
- **Type**: Donut chart
- **Group**: sms_opt_in
- **Value**: COUNT(borrower_id)
- **Colors**: Orange (Yes), Gray (No)
- **Center Label**: Percentage opted-in
- **Title**: "SMS Opt-In Status"

---

### Bottom: Interactive Filters
> The filter bar now includes a **Run Query Only** button and a companion
> **Download CSV** button, placed at the right edge.  Query progress is shown in
> the pipeline log panel above, and a semi‑transparent overlay prevents
> interaction while data is loading.  Slider controls are debounced so that
> small adjustments do not immediately trigger a refresh.

#### Filter Bar Configuration
1. **Marketing Category** (Multi-select dropdown)
   - Type: List control
   - Options: All categories
   - Default: All selected

2. **LTV Ratio** (Range slider)
   - Type: Slider
   - Min: 0%
   - Max: 100%
   - Default: 0-80%

3. **Rate Spread** (Range slider)
   - Type: Slider
   - Min: 0%
   - Max: 3%
   - Default: 0-3%

4. **Engagement Filters** (Checkboxes)
   - Type: Multi-select list
   - Options: 
     - ☐ Email Active
     - ☐ Mobile App Active
     - ☐ Paperless Enrolled
     - ☐ SMS Opted-In
   - Behavior: AND logic (all must be true)

---

## Color Scheme

### Primary Colors
- **Blue**: #3498DB (Data, General)
- **Green**: #2ECC71 (Positive, Savings)
- **Orange**: #F39C12 (Warning, Hot Leads)
- **Red**: #E74C3C (Urgent, Immediate Action)
- **Purple**: #9B59B6 (Neutral, Metrics)

### Secondary Colors
- **Gray**: #95A5A6 (Inactive, Ineligible)
- **Yellow**: #F1C40F (Watchlist)
- **Dark Blue**: #2C3E50 (Text, Headers)

### Gradients
- Light to dark variations for depth
- Use for KPI tiles and bars

---

## Dashboard Settings

### Refresh Schedule
- **Mode**: Direct Query (real-time)
- **Alternative**: SPICE with hourly refresh

### Permissions
- **Owner**: POC Administrator
- **Viewers**: Marketing Team, Executive Team
- **Co-owners**: Data Analytics Team

### Export Options
- ✓ Enable PDF export
- ✓ Enable Excel export
- ✓ Enable CSV export for underlying data

### Mobile Responsiveness
- ✓ Enable mobile layout
- ✓ Stack visualizations vertically
- ✓ Maintain filter bar at top

---

## Implementation Checklist

- [ ] Run `python scripts/setup_quicksight.py`
- [ ] Create new analysis from RefiReadyDataset
- [ ] Add calculated fields (rate_spread, marketing_category, full_name)
- [ ] Create Row 1: KPI tiles
- [ ] Create Row 2: Category bar chart + scatter plot
- [ ] Create Row 3: Top 10 chart + heatmap
- [ ] Create Row 4: Engagement donut charts
- [ ] Add filter controls
- [ ] Set color scheme
- [ ] Test all filters
- [ ] Publish dashboard as "Refi-Ready Borrower Dashboard"
- [ ] Share with stakeholders
- [ ] Set up email subscriptions (optional)

---

## Usage Tips

### For Executives
- Focus on KPI tiles for quick overview
- Use marketing category chart to prioritize campaigns
- Review top savings opportunities for ROI estimates

### For Marketing Teams
- Use filters to segment audiences
- Export filtered lists for campaign uploads
- Monitor engagement metrics to optimize channels

### For Data Analysts
- Explore scatter plot for correlations
- Use heatmap to identify sweet spots
- Drill down into specific borrower details

---

## Maintenance

### Weekly
- Verify data freshness
- Check for data quality issues
- Review filter usage analytics

### Monthly
- Add new calculated fields based on feedback
- Update color schemes if needed
- Review and optimize SPICE usage (if enabled)

### Quarterly
- Evaluate new visualization needs
- Add historical comparisons
- Update documentation

---

## Advanced Features (Optional)

### Drill-Down Actions
- Click borrower → Show detailed profile
- Click category → Filter entire dashboard

### Email Subscriptions
- Daily digest of "Immediate Action" count
- Weekly summary PDF to executives

### Embedded Analytics
- Embed dashboard in internal portal
- Generate public sharing URL (with security)

### ML Insights (Enterprise Only)
- Auto-detect anomalies
- Forecast future refinance opportunities
- Natural language queries

---

## Support

For dashboard issues:
- QuickSight User Guide: https://docs.aws.amazon.com/quicksight/
- Internal POC documentation: QUICKSIGHT_SETUP.md
- Setup script: `python scripts/setup_quicksight.py`
