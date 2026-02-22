#!/usr/bin/env python3
"""
Setup AWS QuickSight for the Refi-Ready POC.
This script will:
1. Check QuickSight subscription status
2. Grant QuickSight access to the S3 bucket
3. Create QuickSight data source (Athena)
4. Create QuickSight dataset (unified_refi_dataset view)
5. Generate a QuickSight dashboard URL for manual setup
"""

import boto3
import logging
import time
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
ENV = "dev"
AWS_REGION = "us-east-1"
S3_BUCKET_NAME = f"refi-ready-poc-{ENV}"
GLUE_DATABASE_NAME = "refi_ready_db"
ATHENA_WORKGROUP = "primary"
ATHENA_OUTPUT_LOCATION = f"s3://{S3_BUCKET_NAME}/athena-results/"

# QuickSight Configuration
QUICKSIGHT_IDENTITY_REGION = "us-east-1"  # QuickSight identity is region-specific
DATA_SOURCE_NAME = "RefiReadyAthenaDataSource"
DATASET_NAME = "RefiReadyDataset"

def get_aws_account_id():
    """Get AWS Account ID."""
    sts_client = boto3.client("sts")
    return sts_client.get_caller_identity()["Account"]

def get_quicksight_user_arn(quicksight_client, aws_account_id):
    """Get the ARN of the QuickSight user (usually admin user)."""
    try:
        # List all users in the account
        response = quicksight_client.list_users(
            AwsAccountId=aws_account_id,
            Namespace='default'
        )
        
        if response['UserList']:
            # Return the first user (typically the admin)
            user_arn = response['UserList'][0]['Arn']
            user_name = response['UserList'][0]['UserName']
            logging.info(f"Found QuickSight user: {user_name}")
            return user_arn, user_name
        else:
            logging.error("No QuickSight users found")
            return None, None
    except Exception as e:
        logging.error(f"Error getting QuickSight user: {e}")
        return None, None

def check_quicksight_subscription(quicksight_client, aws_account_id):
    """Check if QuickSight subscription is active."""
    try:
        response = quicksight_client.describe_account_subscription(
            AwsAccountId=aws_account_id
        )
        
        subscription_status = response['AccountInfo']['AccountSubscriptionStatus']
        logging.info(f"QuickSight subscription status: {subscription_status}")
        
        if subscription_status in ['ACCOUNT_CREATED', 'ACTIVE']:
            logging.info("✓ QuickSight is already subscribed")
            return True
        else:
            logging.warning(f"QuickSight subscription status: {subscription_status}")
            return False
    except quicksight_client.exceptions.ResourceNotFoundException:
        logging.warning("✗ QuickSight is not subscribed for this AWS account")
        return False
    except Exception as e:
        logging.error(f"Error checking QuickSight subscription: {e}")
        return False

def grant_s3_access_to_quicksight(s3_client, bucket_name, aws_account_id):
    """Grant QuickSight read access to S3 bucket."""
    logging.info(f"Granting QuickSight access to S3 bucket '{bucket_name}'...")
    
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "QuickSightAccess",
                "Effect": "Allow",
                "Principal": {
                    "Service": "quicksight.amazonaws.com"
                },
                "Action": [
                    "s3:GetObject",
                    "s3:GetObjectVersion",
                    "s3:ListBucket"
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*"
                ],
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": aws_account_id
                    }
                }
            }
        ]
    }
    
    try:
        # Get existing policy if any
        try:
            existing_policy = s3_client.get_bucket_policy(Bucket=bucket_name)
            existing_policy_dict = json.loads(existing_policy['Policy'])
            
            # Check if QuickSight access already exists
            quicksight_statement_exists = any(
                stmt.get('Sid') == 'QuickSightAccess' 
                for stmt in existing_policy_dict.get('Statement', [])
            )
            
            if quicksight_statement_exists:
                logging.info("QuickSight access already granted in bucket policy")
                return True
            else:
                # Add QuickSight statement to existing policy
                existing_policy_dict['Statement'].extend(bucket_policy['Statement'])
                s3_client.put_bucket_policy(
                    Bucket=bucket_name,
                    Policy=json.dumps(existing_policy_dict)
                )
                logging.info("✓ Added QuickSight access to existing bucket policy")
                return True
        except s3_client.exceptions.NoSuchBucketPolicy:
            # No existing policy, create new one
            s3_client.put_bucket_policy(
                Bucket=bucket_name,
                Policy=json.dumps(bucket_policy)
            )
            logging.info("✓ Created new bucket policy with QuickSight access")
            return True
    except Exception as e:
        logging.error(f"Error granting S3 access to QuickSight: {e}")
        return False

def create_quicksight_data_source(quicksight_client, aws_account_id, user_arn):
    """Create QuickSight data source for Athena."""
    logging.info(f"Creating QuickSight data source '{DATA_SOURCE_NAME}'...")
    
    data_source_id = DATA_SOURCE_NAME.lower().replace(" ", "-")
    
    try:
        # Check if data source already exists
        try:
            quicksight_client.describe_data_source(
                AwsAccountId=aws_account_id,
                DataSourceId=data_source_id
            )
            logging.info(f"Data source '{DATA_SOURCE_NAME}' already exists")
            return data_source_id
        except quicksight_client.exceptions.ResourceNotFoundException:
            pass
        
        # Create new data source
        response = quicksight_client.create_data_source(
            AwsAccountId=aws_account_id,
            DataSourceId=data_source_id,
            Name=DATA_SOURCE_NAME,
            Type='ATHENA',
            DataSourceParameters={
                'AthenaParameters': {
                    'WorkGroup': ATHENA_WORKGROUP
                }
            },
            Permissions=[
                {
                    'Principal': user_arn,
                    'Actions': [
                        'quicksight:DescribeDataSource',
                        'quicksight:DescribeDataSourcePermissions',
                        'quicksight:PassDataSource',
                        'quicksight:UpdateDataSource',
                        'quicksight:DeleteDataSource',
                        'quicksight:UpdateDataSourcePermissions'
                    ]
                }
            ]
        )
        
        logging.info(f"✓ Created QuickSight data source: {data_source_id}")
        return data_source_id
    except Exception as e:
        logging.error(f"Error creating QuickSight data source: {e}")
        return None

def create_quicksight_dataset(quicksight_client, aws_account_id, data_source_id, user_arn):
    """Create QuickSight dataset from the unified_refi_dataset view."""
    logging.info(f"Creating QuickSight dataset '{DATASET_NAME}'...")
    
    dataset_id = DATASET_NAME.lower().replace(" ", "-")
    
    try:
        # Check if dataset already exists
        try:
            quicksight_client.describe_data_set(
                AwsAccountId=aws_account_id,
                DataSetId=dataset_id
            )
            logging.info(f"Dataset '{DATASET_NAME}' already exists")
            return dataset_id
        except quicksight_client.exceptions.ResourceNotFoundException:
            pass
        
        # Create new dataset
        response = quicksight_client.create_data_set(
            AwsAccountId=aws_account_id,
            DataSetId=dataset_id,
            Name=DATASET_NAME,
            PhysicalTableMap={
                'refi-table': {
                    'RelationalTable': {
                        'DataSourceArn': f"arn:aws:quicksight:{AWS_REGION}:{aws_account_id}:datasource/{data_source_id}",
                        'Catalog': 'AwsDataCatalog',
                        'Schema': GLUE_DATABASE_NAME,
                        'Name': 'unified_refi_dataset',
                        'InputColumns': [
                            {'Name': 'borrower_id', 'Type': 'STRING'},
                            {'Name': 'first_name', 'Type': 'STRING'},
                            {'Name': 'last_name', 'Type': 'STRING'},
                            {'Name': 'current_interest_rate', 'Type': 'DECIMAL'},
                            {'Name': 'market_rate_offer', 'Type': 'DECIMAL'},
                            {'Name': 'ltv_ratio', 'Type': 'DECIMAL'},
                            {'Name': 'monthly_savings_est', 'Type': 'DECIMAL'},
                            {'Name': 'paperless_billing', 'Type': 'BIT'},
                            {'Name': 'email_open_last_30d', 'Type': 'BIT'},
                            {'Name': 'mobile_app_login_last_30d', 'Type': 'BIT'},
                            {'Name': 'sms_opt_in', 'Type': 'BIT'}
                        ]
                    }
                }
            },
            LogicalTableMap={
                'refi-logical-table': {
                    'Alias': 'RefiData',
                    'Source': {
                        'PhysicalTableId': 'refi-table'
                    },
                    'DataTransforms': [
                        {
                            'CreateColumnsOperation': {
                                'Columns': [
                                    {
                                        'ColumnName': 'rate_spread',
                                        'ColumnId': 'rate_spread',
                                        'Expression': '{current_interest_rate} - {market_rate_offer}'
                                    },
                                    {
                                        'ColumnName': 'full_name',
                                        'ColumnId': 'full_name',
                                        'Expression': 'concat({first_name}, \' \', {last_name})'
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
            ImportMode='DIRECT_QUERY',
            Permissions=[
                {
                    'Principal': user_arn,
                    'Actions': [
                        'quicksight:DescribeDataSet',
                        'quicksight:DescribeDataSetPermissions',
                        'quicksight:PassDataSet',
                        'quicksight:DescribeIngestion',
                        'quicksight:ListIngestions',
                        'quicksight:UpdateDataSet',
                        'quicksight:DeleteDataSet',
                        'quicksight:CreateIngestion',
                        'quicksight:CancelIngestion',
                        'quicksight:UpdateDataSetPermissions'
                    ]
                }
            ]
        )
        
        logging.info(f"✓ Created QuickSight dataset: {dataset_id}")
        return dataset_id
    except Exception as e:
        logging.error(f"Error creating QuickSight dataset: {e}")
        logging.error(f"Error details: {str(e)}")
        return None

def print_quicksight_instructions(aws_account_id, dataset_id):
    """Print instructions for creating QuickSight dashboard."""
    print("\n" + "="*80)
    print("QUICKSIGHT SETUP COMPLETED")
    print("="*80)
    print("\nQuickSight resources have been created:")
    print(f"  ✓ Data Source: {DATA_SOURCE_NAME} (Athena)")
    print(f"  ✓ Dataset: {DATASET_NAME}")
    print("\nNext Steps - Create Dashboard:")
    print("="*80)
    print("\n1. Open QuickSight Console:")
    print(f"   https://{QUICKSIGHT_IDENTITY_REGION}.quicksight.aws.amazon.com/sn/start")
    print("\n2. Create a New Analysis:")
    print("   - Click 'Analyses' in the left menu")
    print("   - Click 'New analysis'")
    print(f"   - Select the dataset: '{DATASET_NAME}'")
    print("   - Click 'Create analysis'")
    print("\n3. Suggested Visualizations:")
    print("   a) KPI Tiles:")
    print("      - Total Refinance-Ready Borrowers (Count of borrower_id)")
    print("      - Total Monthly Savings (Sum of monthly_savings_est)")
    print("      - Average Rate Spread (Avg of rate_spread)")
    print("\n   b) Bar Chart:")
    print("      - X-axis: Marketing Category")
    print("      - Value: Count of Borrowers")
    print("      - Title: 'Borrowers by Marketing Category'")
    print("\n   c) Scatter Plot:")
    print("      - X-axis: current_interest_rate")
    print("      - Y-axis: market_rate_offer")
    print("      - Size: monthly_savings_est")
    print("      - Color: Marketing Category")
    print("      - Title: 'Rate Comparison Analysis'")
    print("\n   d) Horizontal Bar Chart:")
    print("      - Y-axis: full_name (Top 10)")
    print("      - Value: monthly_savings_est")
    print("      - Title: 'Top Savings Opportunities'")
    print("\n   e) Pie Chart:")
    print("      - Group by: Engagement metrics (email_open_last_30d, mobile_app_login_last_30d)")
    print("      - Value: Count")
    print("\n4. Publish Dashboard:")
    print("   - Click 'Share' -> 'Publish dashboard'")
    print("   - Give it a name: 'Refi-Ready Borrower Dashboard'")
    print("   - Set permissions as needed")
    print("\n5. Share Dashboard (Optional):")
    print("   - Click 'Share' on the published dashboard")
    print("   - Add users or generate embed code")
    print("="*80 + "\n")

def main():
    """Main function to set up QuickSight."""
    logging.info("Starting QuickSight setup...")
    
    try:
        # Get AWS Account ID
        aws_account_id = get_aws_account_id()
        logging.info(f"AWS Account ID: {aws_account_id}")
        
        # Initialize AWS clients
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        quicksight_client = boto3.client("quicksight", region_name=QUICKSIGHT_IDENTITY_REGION)
        
        # 1. Check QuickSight subscription
        if not check_quicksight_subscription(quicksight_client, aws_account_id):
            print("\n" + "="*80)
            print("QUICKSIGHT SUBSCRIPTION REQUIRED")
            print("="*80)
            print("\nAWS QuickSight is not subscribed for this account.")
            print("\nTo subscribe to QuickSight:")
            print(f"1. Visit: https://console.aws.amazon.com/quicksight/home?region={AWS_REGION}")
            print("2. Click 'Sign up for QuickSight'")
            print("3. Choose 'Standard' or 'Enterprise' edition")
            print("4. Follow the subscription wizard")
            print("\nNote: QuickSight has a 30-day free trial, then charges per user/month")
            print("      Standard: $9/user/month, Enterprise: $18/user/month")
            print("="*80 + "\n")
            return
        
        # 2. Get QuickSight user
        user_arn, user_name = get_quicksight_user_arn(quicksight_client, aws_account_id)
        if not user_arn:
            logging.error("No QuickSight user found. Please create a user in QuickSight first.")
            return
        
        # 3. Grant S3 access to QuickSight
        grant_s3_access_to_quicksight(s3_client, S3_BUCKET_NAME, aws_account_id)
        
        # 4. Create QuickSight data source
        data_source_id = create_quicksight_data_source(quicksight_client, aws_account_id, user_arn)
        if not data_source_id:
            logging.error("Failed to create data source")
            return
        
        # 5. Create QuickSight dataset
        dataset_id = create_quicksight_dataset(quicksight_client, aws_account_id, data_source_id, user_arn)
        if not dataset_id:
            logging.error("Failed to create dataset")
            return
        
        # 6. Print instructions
        print_quicksight_instructions(aws_account_id, dataset_id)
        
        logging.info("QuickSight setup completed successfully!")
        
    except Exception as e:
        logging.error(f"Error during QuickSight setup: {e}")
        raise

if __name__ == "__main__":
    main()
