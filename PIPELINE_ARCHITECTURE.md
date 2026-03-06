# Refi-Ready POC: Pipeline Architecture & How It Works

## Goal
Build an automated AWS pipeline that:
1. **Links borrower data** from multiple sources
2. **Resolves borrower identities** using AWS Entity Resolution
3. **Evaluates refinance eligibility** using 2026 market conditions
4. **Produces a targeted "refi-ready" borrower audience file**

---

## How We Accomplish This Goal

### **Phase 1: Data Ingestion & Storage**

#### What We Do:
```
Local CSV Files → AWS S3 Raw Zone
   ├── borrower_information.csv
   ├── loan_information.csv
   ├── market_equity.csv
   └── borrower_engagement.csv
```

#### How It Works:
- **Source**: Four source CSV files containing complementary borrower data
- **Storage**: Upload to S3 bucket `s3://refi-ready-poc-dev/raw/`
- **Purpose**: Create a centralized, scalable data repository accessible to AWS services
- **Code Location**: `scripts/run_pipeline.py` → `upload_data_to_s3()`

#### File Descriptions:
| File | Purpose | Key Fields |
|------|---------|-----------|
| `borrower_information.csv` | Core borrower identity | borrower_id, first_name, last_name, property_id |
| `loan_information.csv` | Current loan details | borrower_id, current_interest_rate |
| `market_equity.csv` | 2026 market conditions | property_id, market_rate_offer, ltv_ratio, monthly_savings_est |
| `borrower_engagement.csv` | Engagement signals | borrower_id, paperless_billing, email_open_last_30d, mobile_app_login_last_30d, sms_opt_in |

---

### **Phase 2: Data Cataloging (AWS Glue)**

#### What We Do:
```
S3 Raw Data → Glue Crawler → Glue Data Catalog
                                    ├── borrower_information_csv
                                    ├── loan_information_csv
                                    ├── market_equity_csv
                                    └── borrower_engagement_csv
```

#### How It Works:
1. **Glue Crawler** (`refi-ready-crawler`) automatically scans the S3 raw zone
2. **Infers schema** from CSV headers and data types
3. **Registers tables** in the Glue Data Catalog with metadata:
   - Column types (bigint, boolean, double, string, etc.)
   - Location (S3 path)
   - Format (CSV with comma delimiter)
   - Record counts (number of rows per table)

#### Why This Matters:
- Makes data **discoverable and queryable** via SQL
- Eliminates manual schema management
- Provides **data lineage** and governance
- Enables downstream analytics tools (Athena, EMR, etc.)

#### Code Location:
`scripts/run_pipeline.py` → `start_glue_crawler()`

#### Execution Timeline:
```
Crawler Status: RUNNING → STOPPING → READY
Typical Duration: 2-4 minutes
```

---

### **Phase 2.5: Entity Resolution (Identity Matching & Deduplication)**

#### What We Do:
```
Cataloged Borrower Records
    ↓
AWS Entity Resolution Matching Workflow
    ↓
Match ID Groups (Identifies Duplicate Records)
    ↓
Glue Table for Resolution Results
    ↓
SQL Ranking & Deduplication (Unified View)
```

#### How It Works:

**Step 1: Configure Entity Resolution**
- Define schema mapping for borrower identity attributes (email, phone, borrower_id, property_id)
- Create matching workflow with rule-based matching on email and phone
- Run Entity Resolution matching job on all cataloged borrower records

**Step 2: Generate Match Output**
- AWS Entity Resolution produces match results with:
  - `match_id`: Canonical identifier grouping duplicate borrowers together
  - `record_id`: Original record identifier
  - `borrower_id`, `email`, `phone`, `property_id`: Original attributes
- Output stored at: `s3://refi-ready-poc-dev/resolved/`

**Step 3: Register Results as Glue Table**
- Create Glue external table pointing to resolved output
- Table name: `entity_resolution_results`
- Enables SQL queries to use match identities in Athena

**Step 4: Deduplicate in Unified View**
- The `unified_refi_dataset` view uses:
  - LEFT JOIN to entity_resolution_results on borrower_id
  - COALESCE(match_id, borrower_id) to group duplicates
  - ROW_NUMBER() to rank borrowers within each match group
  - WHERE rank = 1 to select one representative per group

#### Why This Matters:
- **Prevents duplicate targeting**: Multiple records for same person are consolidated
- **Improves data quality**: Identifies and groups variations (e.g., "Jon" vs "John" Smith)
- **Reduces wasted marketing spend**: Each unique borrower appears once in output
- **Creates "single customer view"**: Essential for accurate refinance opportunity analysis
- **Enables governance**: Explicit match_id artifacts for compliance/audit purposes

#### Code Location:
- Workflow creation: `scripts/run_pipeline.py` → `create_entity_resolution_workflow()`
- Job execution: `scripts/run_pipeline.py` → `start_matching_job()`
- Results table: `scripts/run_pipeline.py` → `create_entity_resolution_results_table()`

---

### **Phase 3: Data Linking & Enrichment (Amazon Athena)**

#### What We Do:
```
Four Separate Tables
        ↓
    JOIN Operations
        ↓
Unified Dataset View
        ↓
Refinance Eligibility Query
        ↓
Qualified Borrower File
```

#### Step 3A: Create Unified View with Deduplication

**SQL Query:**
```sql
CREATE OR REPLACE VIEW unified_refi_dataset AS
WITH ranked_borrowers AS (
    SELECT
        bi.borrower_id,
        bi.first_name,
        bi.last_name,
        li.current_interest_rate,
        me.market_rate_offer,
        me.ltv_ratio,
        me.monthly_savings_est,
        be.paperless_billing,
        be.email_open_last_30d,
        be.mobile_app_login_last_30d,
        be.sms_opt_in,
        COALESCE(er.match_id, CAST(bi.borrower_id AS VARCHAR)) AS match_id,
        ROW_NUMBER() OVER (PARTITION BY COALESCE(er.match_id, CAST(bi.borrower_id AS VARCHAR)) ORDER BY bi.borrower_id) AS rank
    FROM borrower_information_csv bi
    LEFT JOIN entity_resolution_results er ON bi.borrower_id = er.borrower_id
    JOIN loan_information_csv li ON bi.borrower_id = li.borrower_id
    JOIN market_equity_csv me ON bi.property_id = me.property_id
    JOIN borrower_engagement_csv be ON bi.borrower_id = be.borrower_id
)
SELECT
    borrower_id, first_name, last_name, current_interest_rate,
    market_rate_offer, ltv_ratio, monthly_savings_est,
    paperless_billing, email_open_last_30d, mobile_app_login_last_30d, sms_opt_in
FROM ranked_borrowers
WHERE rank = 1
```

**How This Links & Deduplicates Data:**
- **Entity Resolution LEFT JOIN**: Groups duplicate records via match_id
- **COALESCE Fallback**: Uses borrower_id if no match found (single records)
- **ROW_NUMBER() Ranking**: Assigns rank within each match group (1 = first, 2 = second, etc.)
- **WHERE rank = 1**: Selects only one representative per group
- **Current Loan Terms**: From loan_information (inner join keeps complete data)
- **2026 Market Opportunity**: From market_equity (property-level data)
- **Customer Engagement**: From borrower_engagement (email/app/SMS signals)

**Example With Duplicates:**
```
Input (61 rows): B001, B002, B003... B052(duplicate of B001), B053(duplicate of B018)...
        ↓ [Entity Resolution identifies matches]
match_id groups:
  - match_001: [B001, B052] → rank 1 = B001, rank 2 = B052
  - match_002: [B018, B053] → rank 1 = B018, rank 2 = B053
  - match_003: [B003] → rank 1 = B003
        ↓ [WHERE rank = 1]
Output (51 unique): B001, B003, B018... (B052, B053 filtered out)
```

**Why This View?**
- Single source of truth for refi analysis
- Prevents duplicate queries
- Improves query performance
- Easy to update when source data changes

---
#### Step 3B: Evaluate Refinance Eligibility

**SQL Query:**
```sql
SELECT
    borrower_id,
    first_name || ' ' || last_name AS name,
    (current_interest_rate - market_rate_offer) AS rate_spread,
    monthly_savings_est,
    CASE
        WHEN (current_interest_rate - market_rate_offer) > 1.25 
            THEN 'Immediate Action'
        WHEN (current_interest_rate - market_rate_offer) > 0.75 
            THEN 'Hot Lead'
        WHEN (current_interest_rate - market_rate_offer) > 0.50 
            THEN 'Watchlist'
        ELSE 'Ineligible'
    END AS marketing_category
FROM unified_refi_dataset
WHERE
    ltv_ratio <= 80                                    -- Equity requirement
    AND (current_interest_rate - market_rate_offer) >= 1.0  -- Rate spread minimum
```

**How This Evaluates Eligibility:**
| Criteria | Logic | Why It Matters |
|----------|-------|----------------|
| **LTV ≤ 80%** | `ltv_ratio <= 80` | Borrower has sufficient home equity; lower default risk |
| **Rate Spread ≥ 1.0%** | `(current_interest_rate - market_rate_offer) >= 1.0` | Potential savings are meaningful for refi to be worthwhile |
| **Rate Spread Tiers** | >1.25%, >0.75%, >0.50% | Prioritize borrowers with highest savings potential |

**Pipeline Outputs Borrower Categories:**
1. **"Immediate Action"** - 125+ bps savings expected
2. **"Hot Lead"** - 75-125 bps savings expected
3. **"Watchlist"** - 50-75 bps savings expected
4. **"Ineligible"** - Doesn't meet minimum criteria

---

#### Step 3C: Query Execution Details

**Performance Characteristics:**
- **Data Source**: Glue Data Catalog tables in S3 + Entity Resolution identity mapping output
- **Query Engine**: Amazon Athena (distributed SQL on S3)
- **Output Location**: `s3://refi-ready-poc-dev/output/athena/`
- **Typical Duration**: 5-10 seconds per query
- **No infrastructure to manage**: Fully serverless

**How Athena Works:**
```
SQL Query → Athena Optimizer → Partitions S3 Scans
    ↓
Parallel Execution on 3000+ Cores
    ↓
Results → S3 CSV File
```

---

### **Phase 4: Audience Generation**

#### Output File Structure

**File Location**: `s3://refi-ready-poc-dev/output/athena/{execution_id}.csv`

**Columns**:
```
borrower_id       - Unique identifier for targeting
name              - Borrower name (first + last)
rate_spread       - Potential rate reduction (percentage points)
monthly_savings   - Estimated monthly payment reduction ($)
marketing_category - Urgency tier for outreach prioritization
```

**Example Output** (if eligibility criteria were met):
```csv
borrower_id,name,rate_spread,monthly_savings_est,marketing_category
B001,John Doe,1.50,250.00,Immediate Action
B003,Jane Smith,0.95,180.00,Hot Lead
B005,Bob Johnson,0.75,145.00,Watchlist
```

#### How This Becomes a Marketing Asset:

The CSV becomes the "refi-ready" audience file that can be:
1. **Imported into marketing automation** (Salesforce, Adobe, etc.)
2. **Used for email campaigns** - Personalized rate offers based on category
3. **Integrated with call centers** - Priority dial lists by category
4. **Analyzed by business teams** - Revenue potential calculations
5. **Combined with engagement data** - Digital channel strategy

---

## Complete Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    REFI-READY POC PIPELINE                          │
└─────────────────────────────────────────────────────────────────────┘

    PHASE 1: DATA INGESTION
    ═══════════════════════
    
    Local Data Files
    ├── borrower_information.csv
    ├── loan_information.csv
    ├── market_equity.csv
    └── borrower_engagement.csv
            ↓
    [S3 Upload]
            ↓
    S3 Raw Zone (s3://refi-ready-poc-dev/raw/)
    
    
    PHASE 2: DATA CATALOGING
    ════════════════════════
    
    S3 Raw Zone
            ↓
    [Glue Crawler Auto-Runs]
    - Scans S3 structure
    - Infers schema (column types, delimiters)
    - Creates metadata
            ↓
    Glue Data Catalog (Database: refi_ready_db)
    ├── borrower_information_csv (8 columns, 31 rows)
    ├── loan_information_csv (2 columns, 31 rows)
    ├── market_equity_csv (4 columns, 31 rows)
    └── borrower_engagement_csv (5 columns, 31 rows)
            ↓
        [Entity Resolution Matching Workflow]
        - Applies schema mapping to borrower identity fields
        - Consolidates duplicate/fragmented identities
        - Produces canonical borrower mapping for downstream use
    
    
    PHASE 3: DATA LINKING & ENRICHMENT
    ══════════════════════════════════
    
    Glue Tables
            ↓
    [Athena Query 1: Join & Enrich]
    - INNER JOIN on borrower_id
    - INNER JOIN on property_id
    - Combine 18 attributes into single view
            ↓
    unified_refi_dataset (View)
    Columns: borrower_id, first_name, last_name, current_interest_rate,
             market_rate_offer, ltv_ratio, monthly_savings_est,
             paperless_billing, email_open_last_30d, mobile_app_login_last_30d, 
             sms_opt_in
            ↓
    [Athena Query 2: Evaluate Eligibility]
    - Calculate rate_spread
    - Apply eligibility filters (LTV ≤ 80%, spread ≥ 1.0%)
    - Tier borrowers (Immediate Action, Hot Lead, Watchlist)
            ↓
    
    PHASE 4: AUDIENCE GENERATION
    ════════════════════════════
    
    Qualified Borrower Results
            ↓
    [Athena Output Format: CSV]
            ↓
    S3 Output Zone
    s3://refi-ready-poc-dev/output/athena/{query_execution_id}.csv
            ↓
    "Refi-Ready" Borrower Audience File
    - Ready for marketing import
    - Prioritized by savings potential
    - Enriched with engagement signals
```

---

## How It Achieves Each Goal

### ✅ **Goal 1: Links Borrower Data**

| Mechanism | How It Works | Result |
|-----------|------------|--------|
| **Glue Crawler** | Auto-discovers and catalogs tables | 4 tables available in Glue |
| **AWS Entity Resolution** | Matches borrower records that represent the same real-world person | Canonical identity layer before joins |
| **SQL JOINs** | Links via borrower_id & property_id | Single unified row per borrower |
| **View Creation** | Creates reusable, pre-joined dataset | `unified_refi_dataset` ready for analysis |

### ✅ **Goal 2: Resolves Borrower Identities**

| Mechanism | How It Works | Result |
|-----------|------------|--------|
| **Schema Mapping** | Maps identity attributes to Entity Resolution input schema | Consistent matching input across records |
| **Matching Workflow** | Identifies records belonging to the same real-world borrower | Duplicate/fragmented identities consolidated |
| **Canonical Identity Output** | Produces trusted borrower-level entity mapping | Cleaner downstream joins and targeting |

### ✅ **Goal 3: Evaluates Refinance Eligibility Using 2026 Market Conditions**

| Mechanism | How It Works | Result |
|-----------|------------|--------|
| **Market Data Input** | market_equity.csv contains 2026 rates & savings | Current market opportunity quantified |
| **LTV Filtering** | Equity threshold ensures borrower qualification | Only borrowers with sufficient equity qualify |
| **Rate Spread Calculation** | `current_rate - market_rate = potential_savings` | Precise savings potential calculated |
| **Category Tiers** | Three-tier system prioritizes highest-value borrowers | Optimized outreach prioritization |

### ✅ **Goal 4: Produces Targeted "Refi-Ready" Borrower Audience File**

| Mechanism | How It Works | Result |
|-----------|------------|--------|
| **CSV Export** | Athena writes query results to S3 CSV | Standard format for data import |
| **Standardized Column Names** | borrower_id, name, rate_spread, savings, category | Compatible with marketing systems |
| **Prioritized Listing** | Sorted/categorized by marketing urgency | Marketing teams know who to contact first |
| **Timestamped Execution** | Each run has unique query_execution_id | Audit trail and version control |

---

## Key Architectural Advantages

### **1. Fully Serverless**
- No EC2 instances to manage
- No infrastructure to provision
- Pay-per-query pricing model
- Auto-scaling built-in

### **2. Scalable**
```
Current: 31 borrowers per file
Can handle: Millions of borrowers
Only costs scale with data volume (not infrastructure)
```

### **3. Automated**
- Glue Crawler runs on schedule (configurable)
- Can trigger pipeline via:
  - S3 event notifications (new data = auto-run)
  - AWS Lambda
  - EventBridge schedules
  - API calls

### **4. Auditable**
- Each Athena query has execution ID
- Results stored with metadata
- Query history available in Athena console
- Data lineage trackable

### **5. Extensible**
Can easily add:
- **Credit score data** → Additional qualification filters
- **Payment history** → Risk assessment
- **Recent refinance attempts** → Avoid fraud
- **Competitor offers** → Competitive rates
- **Digital engagement data** → Channel preference scoring

---

## 2026 Market Conditions Implementation

### How Market Rates Are Applied:

**Current State (2025):**
```
Borrower: 5.5% rate
Cost: $2,500/month
```

**2026 Market Opportunity (From market_equity.csv):**
```
Market Rate: 4.0%
Potential Cost: $2,250/month
Monthly Savings: $250
Annual Savings: $3,000
```

**Eligibility Decision:**
```
IF (current_rate - market_rate) >= 1.0% 
   AND ltv_ratio <= 80%
THEN borrower is "refi-ready"
```

This data-driven approach ensures:
- ✓ Only offering refi when economically beneficial
- ✓ Considering 2026 market rates (not historical)
- ✓ Focusing on borrowers with equity
- ✓ Quantifying borrower value for prioritization

---

## Execution Summary

### What Happened When We Ran The POC:

```
START: 2026-02-20 20:13:08
├─ PHASE 1: Uploaded 4 CSV files to S3 ✓
│  └─ 31 borrowers + associated attributes
│
├─ PHASE 2: Glue Crawler executed ✓
│  └─ 2-4 minutes to scan data & create schema
│
├─ PHASE 2.5: Entity Resolution matching executed ✓
│  └─ Borrower records consolidated into canonical identities
│
├─ PHASE 3: Athena Queries executed ✓
│  ├─ View creation: 5 seconds
│  └─ Eligibility query: 5 seconds
│
└─ PHASE 4: Results generated ✓
└─ Output: s3://refi-ready-poc-dev/output/athena/6efa3e3e-2b0b-44c8-84ac-bf118a9fb49a.csv
   
END: 2026-02-20 20:24:59
TOTAL TIME: ~12 minutes (mostly Glue crawler)

RESULT: Automated pipeline executing end-to-end with zero manual intervention
```

---

## Next Steps for Production

### To Deploy at Scale:

1. **Increase Data Volume**
   - Connect to real borrower databases
   - Update market_equity.csv with daily rate feeds

2. **Add Automation**
   - S3 event triggers on new data arrival
   - Lambda to orchestrate pipeline
   - CloudWatch alarms on failures

3. **Enhance Targeting**
   - Add engagement scoring algorithm
   - Integrate with CRM for current campaign status
   - Cross-reference with recent refinances

4. **Optimize Output**
   - Add segment-specific messaging
   - Include rate lock information
   - Attach closing cost estimates

5. **Monitor & Improve**
   - Track refi conversion rates by category
   - A/B test outreach messaging
   - Adjust eligibility thresholds based on results

---

## Conclusion

Our pipeline accomplishes the goal through:

1. **Automated Data Collection** - Centralizes borrower data in S3
2. **Intelligent Cataloging** - Makes data discoverable via Glue
3. **Identity Resolution** - Matches duplicate borrower records into canonical entities
4. **Smart Linking** - Combines 4 data sources via SQL joins
5. **Eligibility Evaluation** - Applies 2026 market conditions & rules
6. **Audience Generation** - Produces marketing-ready borrower file

The result: **A fully automated, serverless, scalable system that identifies "refi-ready" borrowers and delivers them to marketing in under 15 minutes.**
