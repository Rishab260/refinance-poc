# Refi-Ready POC

This project is a Proof-of-Concept for a serverless data pipeline on AWS to identify refinance opportunities.

## 🎯 Current Status: FULLY OPERATIONAL ✅

- ✅ **Data Pipeline:** Successfully processing 51 borrowers
- ✅ **S3 Storage:** All CSV files uploaded and ready
- ✅ **Entity Resolution:** Configured and integrated
- ✅ **Data Analysis:** 10 refinance-eligible borrowers identified
- ✅ **Visualization:** Jupyter dashboard ready with interactive plots
- 🚀 **Quick Start:** Run `bash launch_dashboard.sh` to view results!

## Architecture Diagram

```
[S3 Raw Zone] -> [AWS Entity Resolution] -> [S3 Resolved Zone] -> [AWS Glue Crawler] -> [Glue Data Catalog] -> [Amazon Athena] -> [S3 Output Zone]
                                                                                                                       ↓
                                                                                                            [Jupyter Dashboard (FREE)]
                                                                                                                       or
                                                                                                            [AWS QuickSight ($19/mo)]
```

## Setup Instructions

1.  **Configure AWS Credentials:**
    *   Ensure your local environment is configured with AWS credentials that have the necessary permissions. You can do this by setting up the `~/.aws/credentials` file or by setting the `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` (if applicable) environment variables.

2.  **Install Python Dependencies:**
    *   It is recommended to use a virtual environment.
    *   ```bash
        pip install boto3
        ```

3.  **Run the Infrastructure Setup Script:**
    *   This script will create the necessary AWS resources.
    *   ```bash
        python scripts/setup_infrastructure.py
        ```

4.  **Run the Pipeline Execution Script:**
    *   This script will upload the data, run the pipeline, and generate the final output.
    *   ```bash
        python scripts/run_pipeline.py
        ```

5.  **Visualize Data (Choose Your Option):**

    **Option A: Jupyter Notebook (FREE) ⭐ Recommended**
    ```bash
    jupyter notebook
    # Open refi_dashboard.ipynb and run all cells
    ```
    - ✅ Completely free
    - ✅ Interactive visualizations with Plotly
    - ✅ Export to HTML, CSV, or share anywhere
    - ✅ Full customization with Python
    - 📖 See [JUPYTER_NOTEBOOK_GUIDE.md](JUPYTER_NOTEBOOK_GUIDE.md)
    
    **Option B: AWS QuickSight (~$19/month)**
    ```bash
    python scripts/setup_quicksight.py
    ```
    - ✅ Professional cloud-based BI tool
    - ✅ Share dashboards with AWS users
    - ✅ Mobile app access
    - 💰 Requires subscription ($9-18/user/month)
    - 📖 See [QUICKSIGHT_SETUP.md](QUICKSIGHT_SETUP.md)

## Quick Start (All-in-One)

For a streamlined setup, use the main orchestration script:

```bash
python run_poc.py
```

This will:
- ✓ Check AWS credentials and IAM roles
- ✓ Set up all infrastructure
- ✓ Run the complete data pipeline
- ✓ Generate refinance-ready borrower output

## Data Visualization with QuickSight

After running the pipeline, you can visualize the results using AWS QuickSight:

1. Run the QuickSight setup: `python scripts/setup_quicksight.py`
2. Follow instructions to create interactive dashboards
3. See [QUICKSIGHT_SETUP.md](QUICKSIGHT_SETUP.md) for:
   - Subscription setup
   - Dashboard templates
   - Visualization recommendations
   - Cost estimates

## IAM Permissions Required

The following IAM permissions are required to run the scripts:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:PutObject",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:DeleteObject",
                "s3:DeleteBucket"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "glue:CreateDatabase",
                "glue:CreateCrawler",
                "glue:StartCrawler",
                "glue:GetCrawler",
                "glue:DeleteCrawler",
                "glue:DeleteDatabase"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "entityresolution:CreateSchemaMapping",
                "entityresolution:CreateMatchingWorkflow",
                "entityresolution:StartMatchingJob",
                "entityresolution:GetMatchingJob"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "athena:CreateNamedQuery",
                "athena:StartQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": "iam:PassRole",
            "Resource": "*"
        }
    ]
}
```

## Example Athena Query

This query is executed by the `run_pipeline.py` script to identify and categorize refinance-eligible borrowers.

```sql
CREATE OR REPLACE VIEW unified_refi_dataset AS
SELECT
    bi.borrower_id,
    bi.first_name,
    bi.last_name,
    li.current_interest_rate,
    me.market_rate_offer,
    me.ltv_ratio,
    me.monthly_savings_est
FROM
    "refi_ready_db"."borrower_information" bi
JOIN
    "refi_ready_db"."loan_information" li ON bi.borrower_id = li.borrower_id
JOIN
    "refi_ready_db"."market_equity" me ON bi.property_id = me.property_id;

SELECT
    borrower_id,
    first_name || ' ' || last_name AS name,
    (current_interest_rate - market_rate_offer) AS rate_spread,
    monthly_savings_est,
    CASE
        WHEN (current_interest_rate - market_rate_offer) > 1.25 THEN 'Immediate Action'
        WHEN (current_interest_rate - market_rate_offer) > 0.75 THEN 'Hot Lead'
        WHEN (current_interest_rate - market_rate_offer) > 0.50 THEN 'Watchlist'
        ELSE 'Ineligible'
    END AS marketing_category
FROM
    unified_refi_dataset
WHERE
    ltv_ratio <= 80
    AND (current_interest_rate - market_rate_offer) >= 1.0;

```
