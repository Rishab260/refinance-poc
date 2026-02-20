# IAM Roles Creation Instructions

Your AWS user doesn't have permissions to create IAM roles. You need to either:
1. Request IAM permissions from your AWS administrator, OR
2. Have your AWS administrator create these roles for you

## Required Roles

### 1. RefiReadyGlueRole

**Using AWS CLI:**
```bash
# Create the role
aws iam create-role \
  --role-name RefiReadyGlueRole \
  --assume-role-policy-document file://iam-policies/glue-role-trust-policy.json \
  --description "Role for AWS Glue Crawler in Refi-Ready POC"

# Attach the inline policy
aws iam put-role-policy \
  --role-name RefiReadyGlueRole \
  --policy-name GlueS3AccessPolicy \
  --policy-document file://iam-policies/glue-role-policy.json

# Attach AWS managed policy
aws iam attach-role-policy \
  --role-name RefiReadyGlueRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole
```

### 2. RefiReadyEntityResolutionRole

**Using AWS CLI:**
```bash
# Create the role
aws iam create-role \
  --role-name RefiReadyEntityResolutionRole \
  --assume-role-policy-document file://iam-policies/entity-resolution-trust-policy.json \
  --description "Role for AWS Entity Resolution in Refi-Ready POC"

# Attach the inline policy
aws iam put-role-policy \
  --role-name RefiReadyEntityResolutionRole \
  --policy-name EntityResolutionS3AccessPolicy \
  --policy-document file://iam-policies/entity-resolution-policy.json
```

## Using AWS Console

If you prefer to use the AWS Console:

1. Go to IAM > Roles > Create role
2. For **RefiReadyGlueRole**:
   - Trusted entity: AWS service > Glue
   - Attach policies: AWSGlueServiceRole
   - Add inline policy with permissions from `glue-role-policy.json`
   
3. For **RefiReadyEntityResolutionRole**:
   - Trusted entity: AWS service > Other > entityresolution.amazonaws.com
   - Add inline policy with permissions from `entity-resolution-policy.json`

## After Role Creation

Once the roles are created, note the ARNs:
- RefiReadyGlueRole ARN: `arn:aws:iam::875786644800:role/RefiReadyGlueRole`
- RefiReadyEntityResolutionRole ARN: `arn:aws:iam::875786644800:role/RefiReadyEntityResolutionRole`
