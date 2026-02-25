from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import boto3
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = BASE_DIR / "templates"

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("REFI_S3_BUCKET", "refi-ready-poc-dev")
S3_OUTPUT_PREFIX = os.getenv("REFI_S3_OUTPUT_PREFIX", "output/")
S3_RAW_PREFIX = os.getenv("REFI_S3_RAW_PREFIX", "raw/")
PIPELINE_SCRIPT = BASE_DIR / "scripts" / "run_pipeline.py"


pipeline_state_lock = threading.Lock()
pipeline_state: dict[str, Any] = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "message": "No run started yet.",
    "last_output": [],
}


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _categorize_marketing(rate_spread: float) -> str:
    if rate_spread > 1.25:
        return "Immediate Action"
    if rate_spread > 0.75:
        return "Hot Lead"
    if rate_spread > 0.50:
        return "Watchlist"
    return "Ineligible"


def _list_generated_output_csv_objects(s3_client: Any) -> list[dict[str, Any]]:
    paginator = s3_client.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_OUTPUT_PREFIX):
        objects.extend(page.get("Contents", []))

    return [
        obj
        for obj in objects
        if obj.get("Key", "").endswith(".csv") and not obj.get("Key", "").endswith(".csv.metadata")
    ]


def _pick_latest_generated_output_key(csv_objects: list[dict[str, Any]]) -> str:
    if not csv_objects:
        raise FileNotFoundError(f"No pipeline output CSV found at s3://{S3_BUCKET_NAME}/{S3_OUTPUT_PREFIX}")

    ordered_csv = sorted(csv_objects, key=lambda obj: obj.get("LastModified"), reverse=True)
    non_fallback = [obj for obj in ordered_csv if "fallback-" not in obj.get("Key", "")]
    fallback = [obj for obj in ordered_csv if "fallback-" in obj.get("Key", "")]

    if non_fallback:
        return non_fallback[0]["Key"]
    return fallback[0]["Key"]


def _get_latest_output_s3_path() -> str:
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    csv_objects = _list_generated_output_csv_objects(s3_client)
    latest_key = _pick_latest_generated_output_key(csv_objects)
    return f"s3://{S3_BUCKET_NAME}/{latest_key}"


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_pipeline_in_background() -> None:
    command = [sys.executable, str(PIPELINE_SCRIPT)]
    process = subprocess.Popen(
        command,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_lines: list[str] = []
    if process.stdout is not None:
        for line in process.stdout:
            clean_line = line.rstrip()
            output_lines.append(clean_line)
            if len(output_lines) > 40:
                output_lines = output_lines[-40:]

            with pipeline_state_lock:
                pipeline_state["last_output"] = output_lines[-20:]
                pipeline_state["message"] = clean_line or "Pipeline running..."

    exit_code = process.wait()

    with pipeline_state_lock:
        pipeline_state["status"] = "succeeded" if exit_code == 0 else "failed"
        pipeline_state["finished_at"] = _timestamp_utc()
        pipeline_state["exit_code"] = exit_code
        pipeline_state["last_output"] = output_lines[-20:]
        pipeline_state["message"] = "Pipeline completed successfully." if exit_code == 0 else "Pipeline failed."

        if exit_code == 0:
            try:
                pipeline_state["source_key"] = _get_latest_output_s3_path()
            except Exception:
                pipeline_state["source_key"] = None
        else:
            pipeline_state["source_key"] = None


def _load_from_cloud_pipeline_output() -> tuple[pd.DataFrame, str]:
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    csv_objects = _list_generated_output_csv_objects(s3_client)
    ordered_csv = sorted(csv_objects, key=lambda obj: obj.get("LastModified"), reverse=True)
    non_fallback = [obj for obj in ordered_csv if "fallback-" not in obj.get("Key", "")]
    fallback = [obj for obj in ordered_csv if "fallback-" in obj.get("Key", "")]

    candidates = non_fallback[:1] if non_fallback else fallback[:1]
    if not candidates:
        raise FileNotFoundError(f"No pipeline output CSV found at s3://{S3_BUCKET_NAME}/{S3_OUTPUT_PREFIX}")

    df = pd.DataFrame()
    source_key = ""
    for obj in candidates:
        key = obj["Key"]
        s3_obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        candidate = pd.read_csv(BytesIO(s3_obj["Body"].read()))
        source_key = f"s3://{S3_BUCKET_NAME}/{key}"
        df = candidate
        break

    if df.empty and not non_fallback:
        df = _derive_from_cloud_raw_data(s3_client)
        source_key = f"s3://{S3_BUCKET_NAME}/{S3_RAW_PREFIX} (derived)"

    rename_map = {
        "name": "full_name",
    }
    df = df.rename(columns=rename_map)

    if "full_name" in df.columns and "first_name" not in df.columns:
        split_name = df["full_name"].astype(str).str.split(" ", n=1, expand=True)
        if split_name.shape[1] >= 1:
            df["first_name"] = split_name.iloc[:, 0].fillna("")
        else:
            df["first_name"] = ""
        if split_name.shape[1] >= 2:
            df["last_name"] = split_name.iloc[:, 1].fillna("")
        else:
            df["last_name"] = ""

    required_fields = {
        "full_name",
        "current_interest_rate",
        "market_rate_offer",
        "ltv_ratio",
        "paperless_billing",
        "email_open_last_30d",
        "mobile_app_login_last_30d",
        "sms_opt_in",
        "city",
        "state",
        "credit_score",
    }

    missing_required = [field for field in required_fields if field not in df.columns]
    if missing_required:
        borrowers = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_information.csv")
        loans = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}loan_information.csv")
        market = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}market_equity.csv")
        engagement = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_engagement.csv")

        enriched = borrowers.merge(loans, on=["borrower_id", "property_id"], how="inner")
        enriched = enriched.merge(market, on="property_id", how="inner")
        enriched = enriched.merge(engagement, on="borrower_id", how="inner")
        enriched["full_name"] = enriched["first_name"] + " " + enriched["last_name"]
        enriched["rate_spread"] = enriched["current_interest_rate"] - enriched["market_rate_offer"]
        enriched["marketing_category"] = enriched["rate_spread"].map(_categorize_marketing)

        keep_cols = [
            "borrower_id",
            "full_name",
            "city",
            "state",
            "credit_score",
            "current_interest_rate",
            "market_rate_offer",
            "monthly_savings_est",
            "ltv_ratio",
            "rate_spread",
            "marketing_category",
            "paperless_billing",
            "email_open_last_30d",
            "mobile_app_login_last_30d",
            "sms_opt_in",
        ]
        df = df.merge(enriched[keep_cols], on="borrower_id", how="left", suffixes=("", "_enriched"))

        for col in keep_cols:
            enriched_col = f"{col}_enriched"
            if col not in df.columns and enriched_col in df.columns:
                df[col] = df[enriched_col]
            elif col in df.columns and enriched_col in df.columns:
                df[col] = df[col].fillna(df[enriched_col])

        drop_cols = [c for c in df.columns if c.endswith("_enriched")]
        if drop_cols:
            df = df.drop(columns=drop_cols)

    if "city" not in df.columns:
        df["city"] = "N/A"
    if "state" not in df.columns:
        df["state"] = "N/A"
    if "credit_score" not in df.columns:
        df["credit_score"] = 0

    if "paperless_billing" not in df.columns:
        df["paperless_billing"] = False
    if "email_open_last_30d" not in df.columns:
        df["email_open_last_30d"] = False
    if "mobile_app_login_last_30d" not in df.columns:
        df["mobile_app_login_last_30d"] = False
    if "sms_opt_in" not in df.columns:
        df["sms_opt_in"] = False

    if "rate_spread" not in df.columns and {"current_interest_rate", "market_rate_offer"}.issubset(set(df.columns)):
        df["rate_spread"] = df["current_interest_rate"] - df["market_rate_offer"]
    if "marketing_category" not in df.columns and "rate_spread" in df.columns:
        df["marketing_category"] = df["rate_spread"].map(_categorize_marketing)
    if "full_name" not in df.columns and {"first_name", "last_name"}.issubset(set(df.columns)):
        df["full_name"] = df["first_name"].astype(str) + " " + df["last_name"].astype(str)

    return df, source_key


def _read_s3_csv(s3_client: Any, key: str) -> pd.DataFrame:
    obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
    return pd.read_csv(BytesIO(obj["Body"].read()))


def _derive_from_cloud_raw_data(s3_client: Any) -> pd.DataFrame:
    borrowers = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_information.csv")
    loans = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}loan_information.csv")
    market = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}market_equity.csv")
    engagement = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_engagement.csv")

    df = borrowers.merge(loans, on=["borrower_id", "property_id"], how="inner")
    df = df.merge(market, on="property_id", how="inner")
    df = df.merge(engagement, on="borrower_id", how="inner")
    df["rate_spread"] = df["current_interest_rate"] - df["market_rate_offer"]
    df["marketing_category"] = df["rate_spread"].map(_categorize_marketing)
    df["full_name"] = df["first_name"].astype(str) + " " + df["last_name"].astype(str)

    df = df[(df["ltv_ratio"] <= 80) & (df["rate_spread"] >= 1.0)].copy()
    return df


def load_dashboard_data() -> tuple[pd.DataFrame, str]:
    df, source_key = _load_from_cloud_pipeline_output()

    bool_cols = [
        "paperless_billing",
        "email_open_last_30d",
        "mobile_app_login_last_30d",
        "sms_opt_in",
    ]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(_to_bool)

    numeric_cols = [
        "current_interest_rate",
        "market_rate_offer",
        "monthly_savings_est",
        "ltv_ratio",
        "rate_spread",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["current_interest_rate", "market_rate_offer", "monthly_savings_est", "ltv_ratio", "rate_spread"])
    df = df.sort_values(by="monthly_savings_est", ascending=False)
    return df, source_key


def load_dashboard_dataframe() -> pd.DataFrame:
    df, _ = load_dashboard_data()
    return df


def build_payload(df: pd.DataFrame, source_key: str) -> dict[str, Any]:
    records = df[
        [
            "borrower_id",
            "full_name",
            "city",
            "state",
            "credit_score",
            "current_interest_rate",
            "market_rate_offer",
            "monthly_savings_est",
            "ltv_ratio",
            "rate_spread",
            "marketing_category",
            "paperless_billing",
            "email_open_last_30d",
            "mobile_app_login_last_30d",
            "sms_opt_in",
        ]
    ].to_dict(orient="records")

    for record in records:
        record["current_interest_rate"] = round(float(record["current_interest_rate"]), 2)
        record["market_rate_offer"] = round(float(record["market_rate_offer"]), 2)
        record["monthly_savings_est"] = round(float(record["monthly_savings_est"]), 2)
        record["ltv_ratio"] = round(float(record["ltv_ratio"]), 2)
        record["rate_spread"] = round(float(record["rate_spread"]), 2)

    categories = ["Immediate Action", "Hot Lead", "Watchlist", "Ineligible"]
    return {
        "records": records,
        "categories": categories,
        "source_key": source_key,
    }


app = FastAPI(title="Refi Findings Dashboard", version="1.0.0")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    try:
        df, source_key = load_dashboard_data()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cloud pipeline output unavailable. Expected latest CSV at "
                f"s3://{S3_BUCKET_NAME}/{S3_OUTPUT_PREFIX}. "
                f"Error: {exc.__class__.__name__}: {exc}"
            ),
        ) from exc
    payload = build_payload(df, source_key)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "data_json": json.dumps(payload),
        },
    )


@app.post("/api/pipeline/run")
def run_pipeline() -> dict[str, Any]:
    if not PIPELINE_SCRIPT.exists():
        raise HTTPException(status_code=404, detail=f"Pipeline script not found: {PIPELINE_SCRIPT}")

    with pipeline_state_lock:
        if pipeline_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline is already running.")

        pipeline_state["status"] = "running"
        pipeline_state["started_at"] = _timestamp_utc()
        pipeline_state["finished_at"] = None
        pipeline_state["exit_code"] = None
        pipeline_state["message"] = "Pipeline started from dashboard."
        pipeline_state["last_output"] = []
        pipeline_state["source_key"] = None

    thread = threading.Thread(target=_run_pipeline_in_background, daemon=True)
    thread.start()

    return {
        "status": pipeline_state["status"],
        "message": pipeline_state["message"],
        "started_at": pipeline_state["started_at"],
    }


@app.get("/api/pipeline/status")
def get_pipeline_status() -> dict[str, Any]:
    with pipeline_state_lock:
        return dict(pipeline_state)
