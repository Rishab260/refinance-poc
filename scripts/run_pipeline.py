import boto3
import logging
import time
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
ENV = "dev"
AWS_REGION = "us-east-1"
S3_BUCKET_NAME = f"refi-ready-poc-{ENV}"
GLUE_DATABASE_NAME = "refi_ready_db"
GLUE_CRAWLER_NAME = "refi-ready-crawler"
ENTITY_RESOLUTION_SCHEMA_NAME = "borrower_schema_v3"
ENTITY_RESOLUTION_WORKFLOW_NAME = "borrower_matching_workflow_v3"
ATHENA_OUTPUT_LOCATION = f"s3://{S3_BUCKET_NAME}/athena-results/"
FINAL_OUTPUT_LOCATION = f"s3://{S3_BUCKET_NAME}/output/"

# IAM Role names
ENTITY_RESOLUTION_ROLE_NAME = "RefiReadyEntityResolutionRole"

# Get AWS Account ID
sts_client = boto3.client("sts")
try:
    AWS_ACCOUNT_ID = sts_client.get_caller_identity()["Account"]
except Exception as e:
    logging.error("Could not determine AWS Account ID. Please check your AWS credentials.")
    exit()

def upload_data_to_s3(s3_client, bucket_name, data_folder):
    """Uploads CSV files from the data folder to the S3 raw directory."""
    logging.info(f"Uploading data to S3 bucket '{bucket_name}'...")
    for filename in os.listdir(data_folder):
        if filename.endswith(".csv"):
            file_path = os.path.join(data_folder, filename)
            s3_client.upload_file(file_path, bucket_name, f"raw/{filename}")
            logging.info(f"Uploaded '{filename}' to 's3://{bucket_name}/raw/{filename}'.")

def create_entity_resolution_schema(er_client, schema_name):
    """Create an AWS Entity Resolution schema mapping."""
    try:
        er_client.get_schema_mapping(schemaName=schema_name)
        logging.info(f"Entity Resolution schema '{schema_name}' already exists.")
        return f"arn:aws:entityresolution:{AWS_REGION}:{AWS_ACCOUNT_ID}:schemamapping/{schema_name}"
    except er_client.exceptions.ResourceNotFoundException:
        logging.info(f"Creating Entity Resolution schema '{schema_name}'...")
        response = er_client.create_schema_mapping(
            schemaName=schema_name,
            description="Borrower Information Schema",
            mappedInputFields=[
                {'fieldName': 'borrower_id', 'type': 'UNIQUE_ID'},
                {'fieldName': 'first_name', 'type': 'NAME_FIRST'},
                {'fieldName': 'last_name', 'type': 'NAME_LAST'},
                {'fieldName': 'email', 'type': 'EMAIL_ADDRESS', 'matchKey': 'email'},
                {'fieldName': 'phone', 'type': 'PHONE_NUMBER', 'matchKey': 'phone'},
                {'fieldName': 'property_id', 'type': 'PROVIDER_ID', 'subType': 'property'},
            ]
        )
        time.sleep(5) # allow schema to be created
        logging.info(f"Entity Resolution schema '{schema_name}' created.")
        # Return the ARN based on the response
        return response.get('schemaArn') or f"arn:aws:entityresolution:{AWS_REGION}:{AWS_ACCOUNT_ID}:schemamapping/{schema_name}"


def wait_for_workflow_available(er_client, workflow_name, timeout_seconds=120, poll_interval_seconds=5):
    """Wait until the Entity Resolution workflow can be read by GetMatchingWorkflow."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            er_client.get_matching_workflow(workflowName=workflow_name)
            return True
        except er_client.exceptions.ResourceNotFoundException:
            time.sleep(poll_interval_seconds)
    return False

def create_entity_resolution_workflow(er_client, workflow_name, schema_name, role_arn, input_source_arn, s3_path):
    """Create an AWS Entity Resolution matching workflow."""
    try:
        er_client.get_matching_workflow(workflowName=workflow_name)
        logging.info(f"Entity Resolution workflow '{workflow_name}' already exists.")
        return True
    except er_client.exceptions.ResourceNotFoundException:
        logging.info(f"Creating Entity Resolution workflow '{workflow_name}'...")
        try:
            er_client.create_matching_workflow(
                workflowName=workflow_name,
                description="Borrower Matching Workflow",
                inputSourceConfig=[
                    {
                        'inputSourceARN': input_source_arn,
                        'schemaName': schema_name
                    },
                ],
                outputSourceConfig=[
                    {
                        'outputS3Path': f"s3://{s3_path}/resolved/",
                        'output': [
                            {
                                'name': 'borrower_id',
                                'hashed': False
                            },
                            {
                                'name': 'email',
                                'hashed': False
                            },
                            {
                                'name': 'phone',
                                'hashed': False
                            },
                            {
                                'name': 'property_id',
                                'hashed': False
                            }
                        ]
                    },
                ],
                resolutionTechniques={
                    'resolutionType': 'RULE_MATCHING',
                    'ruleBasedProperties': {
                        'rules': [
                            {
                                'ruleName': 'ExactMatch',
                                'matchingKeys': [
                                    'email', 'phone'
                                ]
                            }
                        ],
                        'attributeMatchingModel': 'ONE_TO_ONE'
                    }
                },
                roleArn=role_arn
            )
            if wait_for_workflow_available(er_client, workflow_name):
                logging.info(f"Entity Resolution workflow '{workflow_name}' created and available.")
                return True
            logging.warning(f"Entity Resolution workflow '{workflow_name}' was created but not yet available.")
            return False
        except Exception as e:
            if 'already exists' in str(e):
                logging.info(f"Workflow {workflow_name} already exists")
                return wait_for_workflow_available(er_client, workflow_name)
            else:
                logging.warning(f"Could not create Entity Resolution workflow: {e}")
                logging.info("Proceeding with pipeline...")
                return False


def start_matching_job(er_client, workflow_name):
    """Start an AWS Entity Resolution matching job and wait for completion."""
    def wait_for_job(job_identifier):
        while True:
            job_status_response = er_client.get_matching_job(workflowName=workflow_name, jobId=job_identifier)
            job_status = job_status_response['Status']
            logging.info(f"Matching job '{job_identifier}' status: {job_status}")
            if job_status in ['SUCCEEDED', 'FAILED']:
                return job_status
            time.sleep(30)

    logging.info(f"Starting matching job for workflow '{workflow_name}'...")
    try:
        response = er_client.start_matching_job(workflowName=workflow_name)
        job_id = response['JobId']
        logging.info(f"Matching job started with ID: {job_id}")
    except er_client.exceptions.ExceedsLimitException:
        logging.warning("Maximum concurrent Entity Resolution jobs reached. Checking for running jobs...")
        jobs_response = er_client.list_matching_jobs(workflowName=workflow_name, maxResults=20)
        running_jobs = [
            job for job in jobs_response.get('jobs', [])
            if job.get('status') in ['PENDING', 'RUNNING']
        ]
        if not running_jobs:
            logging.warning("No running matching jobs found despite quota error. Skipping Entity Resolution step.")
            return

        running_jobs.sort(key=lambda job: job.get('startTime') or job.get('createdAt'), reverse=True)
        job_id = running_jobs[0]['jobId']
        logging.info(f"Waiting for existing matching job to complete: {job_id}")
        status = wait_for_job(job_id)
        if status == 'FAILED':
            logging.error("Existing matching job failed. Please check Entity Resolution job logs.")
            return
        logging.info("Existing matching job completed successfully.")
        return

    status = wait_for_job(job_id)

    if status == 'FAILED':
        logging.error(f"Matching job failed. Please check the logs in the AWS console.")
        exit()
    
    logging.info("Matching job completed successfully.")


def start_glue_crawler(glue_client, crawler_name):
    """Start a Glue crawler and wait for completion."""
    logging.info(f"Starting Glue crawler '{crawler_name}'...")
    glue_client.start_crawler(Name=crawler_name)

    while True:
        crawler_status_response = glue_client.get_crawler(Name=crawler_name)
        status = crawler_status_response['Crawler']['State']
        logging.info(f"Crawler status: {status}")
        if status == 'READY':
            break
        time.sleep(30)
    
    logging.info("Glue crawler run completed successfully.")

def execute_athena_query(athena_client, query, database, output_location):
    """Execute an Athena query and wait for completion."""
    logging.info("Executing Athena query...")
    logging.info(f"Query: {query}")
    
    try:
        response = athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': output_location}
        )
        query_execution_id = response['QueryExecutionId']
        logging.info(f"Query started with execution ID: {query_execution_id}")

        while True:
            query_status_response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)
            status = query_status_response['QueryExecution']['Status']['State']
            logging.info(f"Query status: {status}")
            if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                break
            time.sleep(5)
        
        if status != 'SUCCEEDED':
            error_msg = query_status_response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
            logging.error(f"Athena query failed: {error_msg}")
            return None
        
        logging.info("Athena query executed successfully.")
        return query_execution_id
    except Exception as e:
        logging.error(f"Error executing Athena query: {e}")
        return None

def main():
    """Main function to run the data pipeline."""
    logging.info("Starting data pipeline execution...")

    # Initialize AWS clients
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    er_client = boto3.client("entityresolution", region_name=AWS_REGION)
    glue_client = boto3.client("glue", region_name=AWS_REGION)
    athena_client = boto3.client("athena", region_name=AWS_REGION)

    # 1. Upload data to S3
    upload_data_to_s3(s3_client, S3_BUCKET_NAME, "data")
    
    # 2. Start Glue Crawler (required for Glue table used by Entity Resolution)
    start_glue_crawler(glue_client, GLUE_CRAWLER_NAME)

    # 3. Create and run Entity Resolution (optional - skip on errors)
    logging.info("\nAttempting Entity Resolution...")
    try:
        er_role_arn = f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{ENTITY_RESOLUTION_ROLE_NAME}"
        borrower_table_arn = f"arn:aws:glue:{AWS_REGION}:{AWS_ACCOUNT_ID}:table/{GLUE_DATABASE_NAME}/borrower_information_csv"

        create_entity_resolution_schema(er_client, ENTITY_RESOLUTION_SCHEMA_NAME)
        workflow_ready = create_entity_resolution_workflow(
            er_client,
            ENTITY_RESOLUTION_WORKFLOW_NAME,
            ENTITY_RESOLUTION_SCHEMA_NAME,
            er_role_arn,
            borrower_table_arn,
            S3_BUCKET_NAME
        )
        if workflow_ready:
            start_matching_job(er_client, ENTITY_RESOLUTION_WORKFLOW_NAME)
            logging.info("✓ Entity Resolution completed")
        else:
            logging.warning("Entity Resolution workflow is not available; skipping matching job.")
    except Exception as e:
        logging.warning(f"Entity Resolution failed (optional component): {e}")
        logging.info("Proceeding with Athena steps...")
    
    # 4. Execute Athena Queries
    view_query = f"""
    CREATE OR REPLACE VIEW unified_refi_dataset AS
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
        be.sms_opt_in
    FROM
        borrower_information_csv bi
    JOIN
        loan_information_csv li ON bi.borrower_id = li.borrower_id
    JOIN
        market_equity_csv me ON bi.property_id = me.property_id
    JOIN
        borrower_engagement_csv be ON bi.borrower_id = be.borrower_id
    """
    execute_athena_query(athena_client, view_query, GLUE_DATABASE_NAME, ATHENA_OUTPUT_LOCATION)
    
    qualification_query = f"""
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
        AND (current_interest_rate - market_rate_offer) >= 1.0
    """
    query_execution_id = execute_athena_query(athena_client, qualification_query, GLUE_DATABASE_NAME, FINAL_OUTPUT_LOCATION)

    if query_execution_id:
        logging.info(f"Final output is being generated at: {FINAL_OUTPUT_LOCATION}{query_execution_id}.csv")
    else:
        logging.warning("Could not generate final output due to query failure")
    
    logging.info("="*80)
    logging.info("DATA PIPELINE EXECUTION COMPLETED")
    logging.info("="*80)
    logging.info(f"✓ Data uploaded to S3: s3://{S3_BUCKET_NAME}/raw/")
    logging.info(f"✓ Glue database created: {GLUE_DATABASE_NAME}")
    logging.info(f"✓ Glue crawler executed")
    logging.info(f"✓ Athena queries executed")
    if query_execution_id:
        logging.info(f"✓ Final results available at: {FINAL_OUTPUT_LOCATION}{query_execution_id}.csv")

if __name__ == "__main__":
    main()
