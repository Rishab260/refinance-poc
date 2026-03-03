#!/usr/bin/env python3
"""
Quick verification script to ensure the dashboard can load data correctly.
Runs a simplified version of the notebook's data loading logic.
"""

import sys

def main():
    print("=" * 70)
    print("  Refi-Ready Dashboard - Data Loading Verification")
    print("=" * 70)
    print()
    
    # Step 1: Check dependencies
    print("📦 Checking dependencies...")
    try:
        import pandas as pd
        print("  ✓ pandas")
    except ImportError:
        print("  ✗ pandas is missing. Install with: pip install pandas")
        return False
    
    try:
        import plotly
        print("  ✓ plotly")
    except ImportError:
        print("  ✗ plotly is missing. Install with: pip install plotly")
        return False
        
    try:
        import numpy as np
        print("  ✓ numpy")
    except ImportError:
        print("  ✗ numpy is missing. Install with: pip install numpy")
        return False
        
    try:
        import s3fs
        print("  ✓ s3fs")
    except ImportError:
        print("  ✗ s3fs is missing. Install with: pip install s3fs")
        return False
    
    print()
    
    # Step 2: Check AWS credentials
    print("🔑 Checking AWS credentials...")
    try:
        import boto3
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        print(f"  ✓ Authenticated as: {identity['Arn']}")
    except Exception as e:
        print(f"  ✗ AWS credentials error: {str(e)}")
        print("     Configure with: aws configure")
        return False
    
    print()
    
    # Step 3: Load data from S3
    print("📊 Loading data from S3...")
    s3_bucket = 'refi-ready-poc-dev'
    
    try:
        borrowers = pd.read_csv(f's3://{s3_bucket}/raw/borrower_information.csv')
        print(f"  ✓ borrower_information.csv ({len(borrowers)} rows)")
    except Exception as e:
        print(f"  ✗ Failed to load borrower_information.csv: {str(e)}")
        return False
    
    try:
        loans = pd.read_csv(f's3://{s3_bucket}/raw/loan_information.csv')
        print(f"  ✓ loan_information.csv ({len(loans)} rows)")
    except Exception as e:
        print(f"  ✗ Failed to load loan_information.csv: {str(e)}")
        return False
    
    try:
        market = pd.read_csv(f's3://{s3_bucket}/raw/market_equity.csv')
        print(f"  ✓ market_equity.csv ({len(market)} rows)")
    except Exception as e:
        print(f"  ✗ Failed to load market_equity.csv: {str(e)}")
        return False
    
    try:
        engagement = pd.read_csv(f's3://{s3_bucket}/raw/borrower_engagement.csv')
        print(f"  ✓ borrower_engagement.csv ({len(engagement)} rows)")
    except Exception as e:
        print(f"  ✗ Failed to load borrower_engagement.csv: {str(e)}")
        return False
    
    print()
    
    # Step 4: Join dataframes
    print("🔗 Joining dataframes...")
    try:
        df = borrowers.merge(loans, on='borrower_id', suffixes=('', '_loan'), how='inner')
        df = df.merge(market, on='property_id', how='inner')
        df = df.merge(engagement, on='borrower_id', how='inner')
        print(f"  ✓ All dataframes joined ({len(df)} rows)")
    except Exception as e:
        print(f"  ✗ Failed to join dataframes: {str(e)}")
        return False
    
    print()
    
    # Step 5: Filter for eligibility
    print("🎯 Filtering for refinance-eligible borrowers...")
    try:
        df_eligible = df[
            (df['ltv_ratio'] <= 80) &
            ((df['current_interest_rate'] - df['market_rate_offer']) >= 1.0)
        ].copy()
        print(f"  ✓ Found {len(df_eligible)} refinance-eligible borrowers")
    except Exception as e:
        print(f"  ✗ Failed to filter data: {str(e)}")
        return False
    
    print()
    
    # Step 6: Display summary
    if len(df_eligible) > 0:
        print("=" * 70)
        print("  ✅ SUCCESS! Dashboard is ready to use.")
        print("=" * 70)
        print()
        print(f"Total Borrowers:          {len(borrowers)}")
        print(f"Refinance-Eligible:       {len(df_eligible)}")
        print(f"Eligibility Rate:         {len(df_eligible)/len(borrowers)*100:.1f}%")
        print()
        print("Top 5 Opportunities:")
        print("-" * 70)
        top5 = df_eligible.nlargest(5, 'monthly_savings_est')[
            ['first_name', 'last_name', 'current_interest_rate', 'market_rate_offer', 'monthly_savings_est']
        ]
        for _, row in top5.iterrows():
            print(f"  {row['first_name']} {row['last_name']:12s} - "
                  f"{row['current_interest_rate']:.1f}% → {row['market_rate_offer']:.1f}% "
                  f"(${row['monthly_savings_est']:.0f}/mo savings)")
        print()
        print("🚀 Next Step: Run the dashboard with:")
        print("   bash launch_dashboard.sh")
        print()

        # try a simple server query against the new /api/data endpoint
        try:
            import requests
            print("🔍 Testing /api/data filter API (app must be running)...")
            resp = requests.get(
                "http://127.0.0.1:8000/api/data",
                params={"category": "Immediate Action", "ltv_min": 60},
                timeout=5,
            )
            if resp.ok:
                print(f"  ✓ API returned {len(resp.json().get('records', []))} records")
            else:
                print(f"  ⚠️ API responded with status {resp.status_code}")
        except ImportError:
            print("  (requests library not installed; skipping API test)")
        except Exception as e:
            print(f"  ⚠️ API request failed: {e}")

        return True
    else:
        print("=" * 70)
        print("  ⚠️  WARNING: No eligible borrowers found!")
        print("=" * 70)
        print()
        print("The data loaded successfully but no borrowers meet the criteria:")
        print("  - LTV ratio ≤ 80%")
        print("  - Rate spread ≥ 1.0%")
        print()
        print("You may need to adjust the filter criteria in the dashboard.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
