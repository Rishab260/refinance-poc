import boto3
import json
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# IAM client
iam_client = boto3.client('iam')

def create_glue_role():
    """Create IAM role for AWS Glue Crawler."""
    role_name = "RefiReadyGlueRole"
    
    # Trust policy for Glue
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "glue.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    # Role policy for Glue
    role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket"
                ],
                "Resource": ["arn:aws:s3:::refi-ready-poc-*", "arn:aws:s3:::refi-ready-poc-*/*"]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "glue:*"
                ],
                "Resource": "*"
            }
        ]
    }
    
    try:
        # Check if role exists
        iam_client.get_role(RoleName=role_name)
        logging.info(f"IAM role '{role_name}' already exists.")
    except iam_client.exceptions.NoSuchEntityException:
        # Create role
        logging.info(f"Creating IAM role '{role_name}'...")
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Role for AWS Glue Crawler in Refi-Ready POC"
        )
        
        # Attach policy
        logging.info(f"Attaching inline policy to '{role_name}'...")
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="GlueS3AccessPolicy",
            PolicyDocument=json.dumps(role_policy)
        )
        
        # Also attach AWS managed policy for Glue
        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
        )
        
        logging.info(f"IAM role '{role_name}' created successfully.")
        time.sleep(10)  # Wait for IAM to propagate
    
    # Get role ARN
    role = iam_client.get_role(RoleName=role_name)
    return role['Role']['Arn']

def create_entity_resolution_role():
    """Create IAM role for AWS Entity Resolution."""
    role_name = "RefiReadyEntityResolutionRole"
    
    # Trust policy for Entity Resolution
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "entityresolution.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    # Role policy for Entity Resolution
    role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket"
                ],
                "Resource": ["arn:aws:s3:::refi-ready-poc-*", "arn:aws:s3:::refi-ready-poc-*/*"]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            }
        ]
    }
    
    try:
        # Check if role exists
        iam_client.get_role(RoleName=role_name)
        logging.info(f"IAM role '{role_name}' already exists.")
    except iam_client.exceptions.NoSuchEntityException:
        # Create role
        logging.info(f"Creating IAM role '{role_name}'...")
        iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Role for AWS Entity Resolution in Refi-Ready POC"
        )
        
        # Attach policy
        logging.info(f"Attaching inline policy to '{role_name}'...")
        iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="EntityResolutionS3AccessPolicy",
            PolicyDocument=json.dumps(role_policy)
        )
        
        logging.info(f"IAM role '{role_name}' created successfully.")
        time.sleep(10)  # Wait for IAM to propagate
    
    # Get role ARN
    role = iam_client.get_role(RoleName=role_name)
    return role['Role']['Arn']

def main():
    """Main function to create IAM roles."""
    logging.info("Starting IAM role creation...")
    
    glue_role_arn = create_glue_role()
    logging.info(f"Glue Role ARN: {glue_role_arn}")
    
    er_role_arn = create_entity_resolution_role()
    logging.info(f"Entity Resolution Role ARN: {er_role_arn}")
    
    logging.info("IAM role creation completed successfully.")
    logging.info(f"\nGlue Role ARN to use: {glue_role_arn}")
    
    return glue_role_arn, er_role_arn

if __name__ == "__main__":
    main()
