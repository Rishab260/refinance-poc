#!/usr/bin/env python3
import argparse
import boto3
import json
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check AWS Entity Resolution schema/workflow/job health for Refi-Ready POC."
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--schema-name", default="borrower_schema_v3", help="Schema mapping name")
    parser.add_argument("--workflow-name", default="borrower_matching_workflow_v3", help="Matching workflow name")
    parser.add_argument("--show-details", action="store_true", help="Print full schema/workflow JSON")
    return parser.parse_args()


def main():
    args = parse_args()

    er_client = boto3.client("entityresolution", region_name=args.region)

    status = {
        "region": args.region,
        "schema": {"name": args.schema_name, "exists": False},
        "workflow": {"name": args.workflow_name, "exists": False},
        "latest_job": {"found": False},
    }

    exit_code = 0

    try:
        schema = er_client.get_schema_mapping(schemaName=args.schema_name)
        status["schema"]["exists"] = True
        status["schema"]["arn"] = schema.get("schemaArn")
        status["schema"]["mapped_fields"] = [
            field.get("fieldName") for field in schema.get("mappedInputFields", [])
        ]
        if args.show_details:
            status["schema"]["details"] = schema
    except er_client.exceptions.ResourceNotFoundException:
        status["schema"]["error"] = "Schema not found"
        exit_code = 1
    except Exception as exc:
        status["schema"]["error"] = str(exc)
        exit_code = 1

    try:
        workflow = er_client.get_matching_workflow(workflowName=args.workflow_name)
        status["workflow"]["exists"] = True
        status["workflow"]["arn"] = workflow.get("workflowArn")
        status["workflow"]["roleArn"] = workflow.get("roleArn")
        status["workflow"]["resolutionType"] = (
            workflow.get("resolutionTechniques", {}).get("resolutionType")
        )
        rules = (
            workflow.get("resolutionTechniques", {})
            .get("ruleBasedProperties", {})
            .get("rules", [])
        )
        status["workflow"]["rules"] = [
            {
                "ruleName": rule.get("ruleName"),
                "matchingKeys": rule.get("matchingKeys", []),
            }
            for rule in rules
        ]
        if args.show_details:
            status["workflow"]["details"] = workflow
    except er_client.exceptions.ResourceNotFoundException:
        status["workflow"]["error"] = "Workflow not found"
        exit_code = 1
    except Exception as exc:
        status["workflow"]["error"] = str(exc)
        exit_code = 1

    if status["workflow"]["exists"]:
        try:
            jobs_resp = er_client.list_matching_jobs(workflowName=args.workflow_name, maxResults=10)
            jobs = jobs_resp.get("jobs", [])
            if jobs:
                jobs_sorted = sorted(
                    jobs,
                    key=lambda entry: entry.get("startTime") or entry.get("createdAt") or "",
                    reverse=True,
                )
                latest_job = jobs_sorted[0]
                status["latest_job"] = {
                    "found": True,
                    "jobId": latest_job.get("jobId"),
                    "status": latest_job.get("status"),
                    "startTime": latest_job.get("startTime"),
                    "endTime": latest_job.get("endTime"),
                }
                if latest_job.get("status") in {"FAILED"}:
                    exit_code = 1
            else:
                status["latest_job"] = {"found": False, "note": "No matching jobs found"}
        except Exception as exc:
            status["latest_job"] = {"found": False, "error": str(exc)}
            exit_code = 1

    print(json.dumps(status, indent=2, default=str))

    if exit_code == 0:
        print("\nHealth check: PASS")
    else:
        print("\nHealth check: FAIL")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
