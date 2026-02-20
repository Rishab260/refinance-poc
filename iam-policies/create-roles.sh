#!/bin/bash
# Script to create required IAM roles for Refi-Ready POC

set -e

echo "Creating IAM roles for Refi-Ready POC..."
echo ""

# Create RefiReadyGlueRole
echo "1. Creating RefiReadyGlueRole..."
aws iam create-role \
  --role-name RefiReadyGlueRole \
  --assume-role-policy-document file://iam-policies/glue-role-trust-policy.json \
  --description "Role for AWS Glue Crawler in Refi-Ready POC" || echo "Role may already exist"

aws iam put-role-policy \
  --role-name RefiReadyGlueRole \
  --policy-name GlueS3AccessPolicy  \
  --policy-document file://iam-policies/glue-role-policy.json || echo "Policy may already be attached"

aws iam attach-role-policy \
  --role-name RefiReadyGlueRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole || echo "Managed policy may already be attached"

echo "✓ RefiReadyGlueRole created"
echo ""

# Create RefiReadyEntityResolutionRole
echo "2. Creating RefiReadyEntityResolutionRole..."
aws iam create-role \
  --role-name RefiReadyEntityResolutionRole \
  --assume-role-policy-document file://iam-policies/entity-resolution-trust-policy.json \
  --description "Role for AWS Entity Resolution in Refi-Ready POC" || echo "Role may already exist"

aws iam put-role-policy \
  --role-name RefiReadyEntityResolutionRole \
  --policy-name EntityResolutionS3AccessPolicy \
  --policy-document file://iam-policies/entity-resolution-policy.json || echo "Policy may already be attached"

echo "✓ RefiReadyEntityResolutionRole created"
echo ""

echo "="
echo "IAM Roles created successfully!"
echo "="
echo ""
echo "You can now run the POC with:"
echo "  python run_poc.py"
echo ""
