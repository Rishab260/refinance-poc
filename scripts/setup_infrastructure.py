import argparse
import boto3
import json
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
# It's recommended to load these from a config file or environment variables
# For this POC, we'll define them here.
# Please replace <env> with your specific value.
ENV = "dev"
AWS_REGION = "us-east-1"  # Defaulting to us-east-1 as no region was specified
S3_BUCKET_NAME = f"refi-ready-poc-{ENV}"
GLUE_DATABASE_NAME = "refi_ready_db"
GLUE_CRAWLER_NAME = "refi-ready-crawler"

def create_s3_bucket(s3_client, bucket_name, region):
    """Create an S3 bucket if it doesn't exist."""
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        logging.info(f"S3 bucket '{bucket_name}' already exists.")
    except s3_client.exceptions.ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code in ['404', 'NoSuchBucket']:
            logging.info(f"Creating S3 bucket '{bucket_name}' in region '{region}'...")
            if region == "us-east-1":
                s3_client.create_bucket(Bucket=bucket_name)
            else:
                s3_client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': region}
                )
            waiter = s3_client.get_waiter('bucket_exists')
            waiter.wait(Bucket=bucket_name)
            logging.info(f"S3 bucket '{bucket_name}' created successfully.")
        elif error_code == '403':
            logging.warning(f"Access denied to S3 bucket '{bucket_name}'. It may already exist and be owned by another account.")
            logging.info(f"Proceeding with assumption that bucket '{bucket_name}' exists.")
        else:
            logging.error(f"Error checking for S3 bucket: {e}")
            raise

def create_glue_database(glue_client, db_name):
    """Create a Glue database if it doesn't exist."""
    try:
        glue_client.get_database(Name=db_name)
        logging.info(f"Glue database '{db_name}' already exists.")
    except glue_client.exceptions.EntityNotFoundException:
        logging.info(f"Creating Glue database '{db_name}'...")
        glue_client.create_database(DatabaseInput={'Name': db_name})
        logging.info(f"Glue database '{db_name}' created successfully.")

def create_glue_crawler(glue_client, crawler_name, db_name, s3_path, role_arn):
    """Create a Glue crawler if it doesn't exist."""
    try:
        glue_client.get_crawler(Name=crawler_name)
        logging.info(f"Glue crawler '{crawler_name}' already exists.")
    except (glue_client.exceptions.EntityNotFoundException, Exception) as e:
        logging.info(f"Creating Glue crawler '{crawler_name}'...")
        try:
            glue_client.create_crawler(
                Name=crawler_name,
                Role=role_arn,
                DatabaseName=db_name,
                Targets={
                    'S3Targets': [
                        {
                            'Path': f"s3://{s3_path}/raw/"
                        },
                    ]
                }
            )
            logging.info(f"Glue crawler '{crawler_name}' created successfully.")
        except Exception as e:
            if 'already exists' in str(e):
                logging.info(f"Glue crawler '{crawler_name}' already exists.")
            else:
                raise


def main():
    """Main function to set up the infrastructure."""
    parser = argparse.ArgumentParser(description="Setup AWS infrastructure for the Refi-Ready POC.")
    parser.add_argument("--glue-role-arn", required=True, help="The ARN of the IAM role for the Glue crawler.")
    args = parser.parse_args()

    logging.info("Starting infrastructure setup...")
    logging.info(f"Using AWS region: {AWS_REGION}")

    # Initialize AWS clients
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    glue_client = boto3.client("glue", region_name=AWS_REGION)

    # 1. Create S3 bucket
    create_s3_bucket(s3_client, S3_BUCKET_NAME, AWS_REGION)

    # 2. Create Glue Database
    create_glue_database(glue_client, GLUE_DATABASE_NAME)

    # 3. Create Glue Crawler
    create_glue_crawler(glue_client, GLUE_CRAWLER_NAME, GLUE_DATABASE_NAME, S3_BUCKET_NAME, args.glue_role_arn)

    logging.info("Infrastructure setup completed successfully.")

if __name__ == "__main__":
    main()
