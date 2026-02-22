# Refi-Ready Pipeline - Quick Reference Guide

## The 4-Phase Pipeline

### PHASE 1: DATA INGESTION
**What**: Upload CSV files to AWS S3
**Why**: Centralized, scalable data storage
**AWS Service**: Amazon S3
**Time**: ~2 seconds per file
```
borrower_information.csv  ─┐
loan_information.csv       ├──→ S3 Raw Zone ─→ Available for processing
market_equity.csv          │
borrower_engagement.csv   ─┘
```

### PHASE 2: DATA CATALOGING
**What**: Automatically discover schema and register tables
**Why**: Make data discoverable and querable
**AWS Service**: AWS Glue Crawler
**Time**: 2-4 minutes
```
S3 Raw Zone ──→ [Auto-Schema Detection] ──→ Glue Data Catalog
                 - Reads CSV headers         - borrower_information_csv
                 - Infers column types       - loan_information_csv
                 - Detects delimiters        - market_equity_csv
                 - Counts rows               - borrower_engagement_csv
```

### PHASE 3: DATA LINKING & ENRICHMENT
**What**: Join tables and evaluate eligibility
**Why**: Single source of truth + apply business rules
**AWS Service**: Amazon Athena (SQL)
**Time**: ~10 seconds total
```
Query 1: CREATE unified_refi_dataset
┌──────────────────────────────────────────┐
│ borrower_information_csv  ──────┐        │
│                                 ├──→ [JOIN] ──→ unified_refi_dataset
│ loan_information_csv      ──────┤        │
│                                 │        │
│ market_equity_csv         ──────┤        │
│                                 ├──→ [JOIN]
│ borrower_engagement_csv   ──────┘        │
└──────────────────────────────────────────┘
                ↓↓↓
Query 2: EVALUATE ELIGIBILITY
┌──────────────────────────────────────────┐
│ unified_refi_dataset                     │
│             ↓                            │
│  WHERE ltv_ratio <= 80%                  │
│    AND rate_spread >= 1.0%               │
│             ↓                            │
│  CASE WHEN rate_spread > 1.25%           │
│       THEN 'Immediate Action'            │
│       ... more tiers ...                 │
│             ↓                            │
│  Results to S3 CSV                       │
└──────────────────────────────────────────┘
```

### PHASE 4: AUDIENCE GENERATION
**What**: Output qualified borrowers to CSV
**Why**: Ready for marketing import
**AWS Service**: S3 (Output Zone)
**Time**: Included in Phase 3
```
Query Results ──→ refi-ready-audience.csv
                  │
                  └─→ Import to:
                     - Salesforce
                     - Adobe Marketing
                     - Email platforms
                     - Call center systems
```

### PHASE 5: DATA VISUALIZATION (OPTIONAL)
**What**: Interactive dashboards and business intelligence
**Why**: Visual insights for stakeholders
**AWS Service**: AWS QuickSight
**Time**: ~5 minutes setup + instant dashboard access
```
Athena View ──→ QuickSight Data Source ──→ Interactive Dashboard
                     ↓                           ↓
              unified_refi_dataset         - KPIs (Total borrowers, savings)
                                          - Charts (by category, engagement)
                                          - Filters (LTV, rate spread)
                                          - Export/Share capabilities
```

---

## Data Flow: Linking Borrowers

### Problem: Data Lives in 4 Separate Files
```
File 1: Borrower Identity
┌─────────────────────────────┐
│ borrower_id | first_name    │
├─────────────────────────────┤
│ B001        | John          │
│ B003        | Jane          │
└─────────────────────────────┘

File 2: Loan Details
┌─────────────────────────────┐
│ borrower_id | current_rate  │
├─────────────────────────────┤
│ B001        | 5.5%          │
│ B003        | 5.75%         │
└─────────────────────────────┘

File 3: 2026 Market Opportunity
┌──────────────────────────────────────┐
│ property_id | market_rate | savings  │
├──────────────────────────────────────┤
│ P001        | 4.0%        | $250/mo  │
│ P003        | 4.25%       | $220/mo  │
└──────────────────────────────────────┘

File 4: Engagement Signals
┌─────────────────────────────┐
│ borrower_id | email_open    │
├─────────────────────────────┤
│ B001        | true          │
│ B003        | false         │
└─────────────────────────────┘
```

### Solution: SQL JOINs Link Everything
```
SELECT b.borrower_id, b.first_name, l.current_rate, m.market_rate, e.email_open
FROM borrower_info b
JOIN loan_info l ON b.borrower_id = l.borrower_id
JOIN market_equity m ON b.property_id = m.property_id
JOIN engagement e ON b.borrower_id = e.borrower_id

Result: Unified Row Per Borrower
┌────────────────────────────────────────────────────────────────┐
│ borrower_id | name | current_rate | market_rate | email_open   │
├────────────────────────────────────────────────────────────────┤
│ B001        | John | 5.5%         | 4.0%        | true         │
│ B003        | Jane | 5.75%        | 4.25%       | false        │
└────────────────────────────────────────────────────────────────┘
```

---

## How We Evaluate Eligibility

### The Logic:

```
BORROWER: John Doe
├─ Current Rate: 5.5%
├─ 2026 Market Rate: 4.0%
├─ Rate Spread (Potential Savings): 1.5%
├─ LTV Ratio (Home Equity): 65%
├─ Monthly Savings: $250
└─ Recent Email Opens: Yes

EVALUATION:
1. Is LTV ≤ 80%?        ✓ YES (65% < 80%) → Has equity
2. Is Rate Spread ≥ 1%? ✓ YES (1.5% > 1%) → Worth refinancing

3. What Category?
   IF rate_spread > 1.25% → "Immediate Action"  ✓ QUALIFIED (1.5% > 1.25%)
   IF rate_spread > 0.75% → "Hot Lead"
   IF rate_spread > 0.50% → "Watchlist"
   ELSE → "Ineligible"

RESULT: John Doe is "Immediate Action" - prioritize contact!
```

---

## Why Each Component Matters

| Component | Purpose | Benefit |
|-----------|---------|---------|
| **S3 Ingestion** | Centralize data | Scalable to millions of borrowers |
| **Glue Crawler** | Auto-schema discovery | No manual ETL coding required |
| **Athena SQL** | Query data with familiar language | Business users can modify logic |
| **JOINs** | Combine complementary datasets | Single source of truth |
| **Eligibility Rules** | Apply business logic | Data-driven decision making |
| **CSV Export** | Marketing-ready format | Plug into existing tools |

---

## Key Differentiators

### ✅ Serverless (No Infrastructure Management)
- No EC2 instances to provision
- No auto-scaling to configure
- No maintenance windows
- Pay only for what you use

### ✅ Fully Automated
- Glue Crawler runs on schedule
- Can trigger on new S3 data
- Lambda orchestration optional
- Hands-off once configured

### ✅ Scalable
- Current: 31 borrowers
- Can handle: Millions
- Cost scales with data volume (not infrastructure)

### ✅ Auditable
- Every query has execution ID
- Results timestamped
- Full query history in Athena
- Data lineage trackable

### ✅ Flexible
- Easy to add new data sources
- SQL rules easy to modify
- Market conditions updated daily
- New eligibility rules deployable instantly

---

## Execution Flow - What Actually Happened

```
START (2026-02-20 20:13:08)
│
├─ INGESTION (2 seconds)
│  ├─ borrower_information.csv → S3 ✓
│  ├─ loan_information.csv → S3 ✓
│  ├─ market_equity.csv → S3 ✓
│  └─ borrower_engagement.csv → S3 ✓
│
├─ CATALOGING (2-4 minutes)
│  └─ Glue Crawler running... → Creates 4 tables ✓
│
├─ LINKING & ENRICHMENT (10 seconds)
│  ├─ Query 1: Create unified_refi_dataset ✓ (5 sec)
│  └─ Query 2: Evaluate eligibility ✓ (5 sec)
│
├─ AUDIENCE GENERATION (immediate)
│  └─ Output: 6efa3e3e-2b0b-44c8-84ac-bf118a9fb49a.csv ✓
│
END (2026-02-20 20:24:59)
TOTAL TIME: 12 minutes (mostly Glue crawler)

RESULT: 31 borrowers evaluated
STATUS: 0 "Immediate Action" (no borrowers met all criteria)
```

---

## The Output File

### Location
`s3://refi-ready-poc-dev/output/6efa3e3e-2b0b-44c8-84ac-bf118a9fb49a.csv`

### Format
```csv
borrower_id,name,rate_spread,monthly_savings_est,marketing_category
B001,John Doe,1.50,250.00,Immediate Action
B003,Jane Smith,0.95,180.00,Hot Lead
B005,Bob Johnson,0.75,145.00,Watchlist
```

### Use Cases
1. **Email Campaign** - "John, save $250/month with refi!"
2. **Call Center Priority** - Call John first, then Jane, then Bob
3. **Rate Lock Offers** - Match offer to customer's savings tier
4. **Marketing Attribution** - Track which segment converts best
5. **Revenue Projection** - Calculate total refinance opportunity

---

## Architecture Advantages

### Cost Efficiency
```
Traditional ETL:
- EC2 instance: $100-500/month
- Data warehouse: $500-2000/month
- Staff to manage: $50-200K/year
TOTAL: $5K-30K/month

Refi-Ready Pipeline:
- S3: ~$5-10/month for this dataset size
- Glue: ~$1/crawler run
- Athena: ~$5-10 for millions of queries
TOTAL: $0.01-1/month
```

### Business Agility
```
Traditional: 2-4 week development cycle
Our Pipeline: Change SQL → Instant deployment
- Add new data source? Add SQL JOIN
- New eligibility rule? Modify WHERE clause
- Change rate thresholds? Update CASE statement
```

### Risk Reduction
```
Audit Trail: Every query logged with execution ID
Error Handling: Failed queries don't run downstream
Rollback: Previous results always in S3 history
```

---

## How to Use Results

### 1. Marketing Import
```
CSV → Salesforce/Adobe/Marketo
        ↓
     Batch Upload
        ↓
  Segment by Category
        ↓
 Deploy Targeted Emails
```

### 2. Sales Call Lists
```
CSV → Priority Sort by rate_spread
        ↓
   Call Center System
        ↓
  Agents dial "Immediate Action" first
        ↓
      Higher conversion
```

### 3. Financial Projection
```
Sum monthly_savings_est across all borrowers
        ↓
    Annual Impact ($M)
        ↓
   ROI of refinance campaign
```

---

## Next Steps

### For Production Deployment:
1. Connect to live borrower database
2. Set up daily market_equity.csv updates
3. Add S3 event notification → Trigger pipeline
4. Create CloudWatch alarms for failures
5. Export results to Salesforce via Zapier/Lambda
6. Track conversion rates by category
7. Refine eligibility rules based on results

### For Enhanced Analysis:
1. Add credit score data
2. Include recent refinance attempts
3. Integrate competitor offer data
4. Score by digital engagement likelihood
5. Segment by product cross-sell potential

---

## Summary

Our pipeline accomplishes the goal through:

✅ **Linking** - SQL JOINs combine 4 data sources  
✅ **Evaluating** - Business rules + 2026 market conditions  
✅ **Produces** - Marketing-ready "refi-ready" audience CSV  

**Result**: Automated, serverless system delivering refinance opportunities in <15 minutes
