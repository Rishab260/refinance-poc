#!/usr/bin/env python3
"""
Comprehensive orchestration script for the Refi-Ready POC.
This script checks prerequisites, sets up infrastructure, and runs the pipeline.
"""

import boto3
import sys
import logging
import subprocess

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration
REQUIRED_ROLES = {
    'glue': 'RefiReadyGlueRole',
    'entity_resolution': 'RefiReadyEntityResolutionRole'
}

def check_aws_credentials():
    """Check if AWS credentials are configured."""
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        logging.info(f"AWS Account: {identity['Account']}")
        logging.info(f"User: {identity['Arn']}")
        return identity['Account']
    except Exception as e:
        logging.error(f"AWS credentials not configured: {e}")
        return None

def check_iam_roles(iam_client):
    """Check if required IAM roles exist."""
    roles = {}
    all_exist = True
    
    for role_type, role_name in REQUIRED_ROLES.items():
        try:
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response['Role']['Arn']
            roles[role_type] = role_arn
            logging.info(f"✓ Found {role_name}: {role_arn}")
        except iam_client.exceptions.NoSuchEntityException:
            logging.error(f"✗ Role '{role_name}' does not exist")
            all_exist = False
        except Exception as e:
            logging.error(f"✗ Error checking role '{role_name}': {e}")
            all_exist = False
    
    return all_exist, roles

def print_role_creation_instructions():
    """Print instructions for creating IAM roles."""
    print("\n" + "="*80)
    print("IAM ROLES REQUIRED")
    print("="*80)
    print("\nThe following IAM roles need to be created:")
    print(f"  1. {REQUIRED_ROLES['glue']}")
    print(f"  2. {REQUIRED_ROLES['entity_resolution']}")
    print("\nInstructions:")
    print("  - See iam-policies/CREATE_ROLES_INSTRUCTIONS.md for detailed setup")
    print("  - Policy files are available in the iam-policies/ directory")
    print("  - Contact your AWS administrator if you don't have IAM permissions")
    print("\nTo create roles using AWS CLI:")
    print("  cd /home/rishabsaini261/codersbrain/refinance-poc")
    print("  bash iam-policies/create-roles.sh")
    print("="*80 + "\n")

def run_infrastructure_setup(glue_role_arn):
    """Run the infrastructure setup script."""
    logging.info("="*80)
    logging.info("STEP 1: INFRASTRUCTURE SETUP")
    logging.info("="*80)
    
    cmd = [
        'python',
        'scripts/setup_infrastructure.py',
        '--glue-role-arn', glue_role_arn
    ]
    
    logging.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        logging.info("✓ Infrastructure setup completed successfully")
        print(result.stdout)
        return True
    else:
        logging.error("✗ Infrastructure setup failed")
        print(result.stderr)
        return False

def run_pipeline():
    """Run the data pipeline."""
    logging.info("\n" + "="*80)
    logging.info("STEP 2: PIPELINE EXECUTION")
    logging.info("="*80)
    
    cmd = ['python', 'scripts/run_pipeline.py']
    
    logging.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        logging.info("✓ Pipeline execution completed successfully")
        print(result.stdout)
        return True
    else:
        logging.error("✗ Pipeline execution failed")
        print(result.stderr)
        return False

def main():
    """Main orchestration function."""
    logging.info("="*80)
    logging.info("REFI-READY POC ORCHESTRATION")
    logging.info("="*80)
    
    # Check AWS credentials
    logging.info("\nChecking AWS credentials...")
    account_id = check_aws_credentials()
    if not account_id:
        sys.exit(1)
    
    # Check IAM roles
    logging.info("\nChecking IAM roles...")
    iam_client = boto3.client('iam')
    roles_exist, roles = check_iam_roles(iam_client)
    
    if not roles_exist:
        print_role_creation_instructions()
        logging.error("\nCannot proceed without required IAM roles.")
        logging.info("\nOnce roles are created, run this script again.")
        sys.exit(1)
    
    # Run infrastructure setup
    if not run_infrastructure_setup(roles['glue']):
        logging.error("\nInfrastructure setup failed. Cannot proceed.")
        sys.exit(1)
    
    # Run pipeline
    if not run_pipeline():
        logging.error("\nPipeline execution failed.")
        sys.exit(1)
    
    logging.info("\n" + "="*80)
    logging.info("POC EXECUTION COMPLETED SUCCESSFULLY")
    logging.info("="*80)
    logging.info("\nCheck the AWS console for:")
    logging.info("  - S3 bucket: refi-ready-poc-dev")
    logging.info("  - Glue database: refi_ready_db")
    logging.info("  - Athena query results")

if __name__ == "__main__":
    main()
