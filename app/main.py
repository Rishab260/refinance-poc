from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import importlib
import re
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import boto3
import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
import logging

# reuse Athena helper from pipeline script
from scripts.run_pipeline import execute_athena_query


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = BASE_DIR / "templates"

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("REFI_S3_BUCKET", "refi-ready-poc-dev")
S3_OUTPUT_PREFIX = os.getenv("REFI_S3_OUTPUT_PREFIX", "output/athena/")
S3_RAW_PREFIX = os.getenv("REFI_S3_RAW_PREFIX", "raw/")
PIPELINE_SCRIPT = BASE_DIR / "scripts" / "run_pipeline.py"

# constants reused for Athena queries
GLUE_DATABASE_NAME = "refi_ready_db"
ATHENA_OUTPUT_LOCATION = f"s3://{S3_BUCKET_NAME}/athena-results/"
FINAL_OUTPUT_LOCATION = f"s3://{S3_BUCKET_NAME}/{S3_OUTPUT_PREFIX}"

ALLOWED_PROMPT_CATEGORIES = ["Immediate Action", "Hot Lead", "Watchlist", "Ineligible"]


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


def _normalize_borrower_id(value: Any) -> str:
    raw = str(value).strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper.startswith("CUST"):
        digits = "".join(ch for ch in upper[4:] if ch.isdigit())
        if digits:
            return str(int(digits))
    return raw


def _find_first_matching_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized_to_actual = {
        re.sub(r"[^a-z0-9]+", "", str(col).strip().lower()): str(col)
        for col in df.columns
    }
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", candidate.strip().lower())
        if key in normalized_to_actual:
            return normalized_to_actual[key]
    return None


def _normalize_output_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    rename_map: dict[str, str] = {}

    borrower_id_col = _find_first_matching_column(
        normalized,
        ["borrower_id", "borrowerid", "custid", "customer_id", "customerid", "external_id", "externalid"],
    )
    if borrower_id_col and borrower_id_col != "borrower_id":
        rename_map[borrower_id_col] = "borrower_id"

    full_name_col = _find_first_matching_column(normalized, ["full_name", "fullname", "name", "customer_name"])
    if full_name_col and full_name_col != "full_name":
        rename_map[full_name_col] = "full_name"

    if rename_map:
        normalized = normalized.rename(columns=rename_map)

    if "borrower_id" in normalized.columns:
        normalized["borrower_id"] = normalized["borrower_id"].map(_normalize_borrower_id)

    if "full_name" in normalized.columns and "first_name" not in normalized.columns:
        split_name = normalized["full_name"].astype(str).str.split(" ", n=1, expand=True)
        if split_name.shape[1] >= 1:
            normalized["first_name"] = split_name.iloc[:, 0].fillna("")
        else:
            normalized["first_name"] = ""
        if split_name.shape[1] >= 2:
            normalized["last_name"] = split_name.iloc[:, 1].fillna("")
        else:
            normalized["last_name"] = ""

    return normalized


def _can_enrich_dashboard_output(df: pd.DataFrame) -> bool:
    return "borrower_id" in df.columns


def _categorize_marketing(rate_spread: float) -> str:
    if rate_spread > 1.25:
        return "Immediate Action"
    if rate_spread > 0.75:
        return "Hot Lead"
    if rate_spread > 0.50:
        return "Watchlist"
    return "Ineligible"


def _list_generated_output_csv_objects(s3_client: Any) -> list[dict[str, Any]]:
    """List all generated CSV outputs from both pipeline and query-only runs."""
    paginator = s3_client.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []
    
    # Search in both output locations:
    # 1. output/ - full pipeline runs
    # 2. output/athena/ - query-only runs
    for prefix in ["output/", S3_OUTPUT_PREFIX]:
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
            objects.extend(page.get("Contents", []))

    return [
        obj
        for obj in objects
        if obj.get("Key", "").endswith(".csv") and not obj.get("Key", "").endswith(".csv.metadata")
    ]


def _last_modified_sort_key(obj: dict[str, Any]) -> datetime:
    last_modified = obj.get("LastModified")
    if isinstance(last_modified, datetime):
        return last_modified
    return datetime.min.replace(tzinfo=timezone.utc)


def _pick_latest_generated_output_key(csv_objects: list[dict[str, Any]]) -> str:
    if not csv_objects:
        raise FileNotFoundError(f"No pipeline output CSV found in s3://{S3_BUCKET_NAME}/output/ or output/athena/")

    ordered_csv = sorted(csv_objects, key=_last_modified_sort_key, reverse=True)
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


# ---------------------------------------------------------------------------
# Athena-only helpers (used by /api/athena endpoints)
# ---------------------------------------------------------------------------

def _default_view_sql() -> str:
    """SQL that creates the *unified_refi_dataset* view.

    Intended to be reused by both the main pipeline and the dashboard's
    ad‑hoc query feature.  Duplication here avoids a circular import.
    """
    return f"""
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


def _build_qualification_sql_from_request(req: PipelineRunRequest | None) -> str:
    """Create eligibility query based on incoming request parameters.

    Behaviour mirrors ``scripts/run_pipeline._build_qualification_sql``
    but operates on the FastAPI request model.
    """
    base = """
    WITH calculated_data AS (
        SELECT
            borrower_id,
            first_name || ' ' || last_name AS name,
            (current_interest_rate - market_rate_offer) AS rate_spread,
            monthly_savings_est,
            ltv_ratio,
            current_interest_rate,
            market_rate_offer,
            email_open_last_30d,
            mobile_app_login_last_30d,
            paperless_billing,
            sms_opt_in,
            CASE
                WHEN (current_interest_rate - market_rate_offer) > 1.25 THEN 'Immediate Action'
                WHEN (current_interest_rate - market_rate_offer) > 0.75 THEN 'Hot Lead'
                WHEN (current_interest_rate - market_rate_offer) > 0.50 THEN 'Watchlist'
                ELSE 'Ineligible'
            END AS marketing_category
        FROM
            unified_refi_dataset
    )
    SELECT
        borrower_id,
        name,
        rate_spread,
        monthly_savings_est,
        marketing_category
    FROM
        calculated_data
    """

    filters: list[str] = []
    if req:
        if req.ltv_min is not None:
            filters.append(f"ltv_ratio >= {req.ltv_min}")
        if req.ltv_max is not None:
            filters.append(f"ltv_ratio <= {req.ltv_max}")
        if req.spread_min is not None:
            filters.append(f"rate_spread >= {req.spread_min}")
        if req.spread_max is not None:
            filters.append(f"rate_spread <= {req.spread_max}")
        if req.category:
            cats = ", ".join(f"'{c.replace("'", "''")}'" for c in req.category)
            filters.append(f"marketing_category IN ({cats})")
        if req.email_active:
            filters.append("lower(email_open_last_30d) = 'true'")
        if req.mobile_active:
            filters.append("lower(mobile_app_login_last_30d) = 'true'")
        if req.paperless_enrolled:
            filters.append("lower(paperless_billing) = 'true'")
        if req.sms_opted_in:
            filters.append("lower(sms_opt_in) = 'true'")

    if filters:
        base += "\nWHERE\n    " + "\n    AND ".join(filters)
    return base


def _get_openai_client() -> Any:
    try:
        openai_module = importlib.import_module("openai")
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="OpenAI SDK is not installed. Add 'openai' to requirements.") from exc

    openai_client_cls = getattr(openai_module, "OpenAI", None)
    if openai_client_cls is None:
        raise HTTPException(status_code=500, detail="OpenAI SDK is unavailable in current environment.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    return openai_client_cls(api_key=api_key)


def _parse_json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _sanitize_generated_sql(sql: Any) -> str:
    if not isinstance(sql, str):
        return ""
    cleaned = sql.strip()
    cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip().rstrip(";")
    return cleaned


def _is_valid_qualification_sql(sql: str) -> bool:
    normalized = sql.strip().lower()
    return "select" in normalized and "from" in normalized


def _friendly_dtype(dtype: Any) -> str:
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    return "string"


@lru_cache(maxsize=1)
def _analyze_input_file_schemas() -> dict[str, Any]:
    files = [
        "borrower_information.csv",
        "loan_information.csv",
        "market_equity.csv",
        "borrower_engagement.csv",
        "account_health_status.csv",
    ]
    data_dir = BASE_DIR / "data"
    schema: dict[str, Any] = {}

    for file_name in files:
        file_path = data_dir / file_name
        if not file_path.exists():
            continue
        try:
            frame = pd.read_csv(file_path, nrows=500)
            schema[file_name] = [
                {"column": str(col), "dtype": _friendly_dtype(dtype)}
                for col, dtype in frame.dtypes.items()
            ]
        except Exception as exc:
            schema[file_name] = [{"column": "__error__", "dtype": str(exc)}]

    return schema


def _schema_context_for_prompt() -> str:
    schema = _analyze_input_file_schemas()
    if not schema:
        return "No local input CSV schema could be read."

    lines: list[str] = []
    for file_name, columns in schema.items():
        if not isinstance(columns, list):
            continue
        col_str = ", ".join(
            f"{entry.get('column')} ({entry.get('dtype')})"
            for entry in columns
            if isinstance(entry, dict) and entry.get("column")
        )
        lines.append(f"- {file_name}: {col_str}")

    return "Input file schema (headers + inferred datatypes):\n" + "\n".join(lines)


def _qualification_sql_from_prompt(prompt: str) -> str:
    client = _get_openai_client()
    schema_context = _schema_context_for_prompt()
    system_prompt = (
        "Convert user intent into an Athena SQL query. "
        "Return strict JSON with one key: qualification_query. "
        f"{schema_context}\n"
        "Rules: query from unified_refi_dataset, target Athena/Presto SQL, "
        "and return only executable SQL text in qualification_query (no markdown). "
        "Choose the simplest query structure that answers the user's question — "
        "use a plain SELECT or aggregation when appropriate, not a CTE unless the complexity requires it. "
        "Select only the columns needed to answer the question."
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )

    content = completion.choices[0].message.content if completion.choices else "{}"
    parsed = _parse_json_object(content)
    sql = _sanitize_generated_sql(parsed.get("qualification_query"))
    if _is_valid_qualification_sql(sql):
        return sql
    return ""


def _run_athena_only(req: PipelineRunRequest | None) -> dict[str, Any]:
    """Execute view + qualification Athena queries and return metadata.

    Does *not* touch S3 raw data, crawlers, or entity resolution.  The
    returned dict contains ``query_execution_id`` and ``s3_path``.
    """
    athena_client = boto3.client("athena", region_name=AWS_REGION)

    # create/refresh view if requested or always run default to ensure latest data
    if req and req.view_query:
        view_sql = req.view_query
    else:
        view_sql = _default_view_sql()
    execute_athena_query(athena_client, view_sql, GLUE_DATABASE_NAME, ATHENA_OUTPUT_LOCATION)

    # qualification
    if req and req.qualification_query:
        qual_sql = req.qualification_query
    else:
        qual_sql = _build_qualification_sql_from_request(req)

    qid = execute_athena_query(
        athena_client,
        qual_sql,
        GLUE_DATABASE_NAME,
        FINAL_OUTPUT_LOCATION,
    )
    if not qid:
        raise HTTPException(status_code=500, detail="Athena qualification query failed")

    return {"query_execution_id": qid, "s3_path": f"{FINAL_OUTPUT_LOCATION}{qid}.csv"}


def _run_pipeline_in_background() -> None:
    command = [sys.executable, str(PIPELINE_SCRIPT)]
    if pipeline_run_args:
        command += pipeline_run_args
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
    ordered_csv = sorted(csv_objects, key=_last_modified_sort_key, reverse=True)
    non_fallback = [obj for obj in ordered_csv if "fallback-" not in obj.get("Key", "")]
    fallback = [obj for obj in ordered_csv if "fallback-" in obj.get("Key", "")]

    candidates = non_fallback + fallback
    if not candidates:
        raise FileNotFoundError(f"No pipeline output CSV found in s3://{S3_BUCKET_NAME}/output/ or output/athena/")

    df = pd.DataFrame()
    source_key = ""
    skipped_candidates: list[str] = []
    for obj in candidates:
        key = obj["Key"]
        try:
            s3_obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
            candidate = pd.read_csv(BytesIO(s3_obj["Body"].read()))
            candidate = _normalize_output_dataframe(candidate)
        except Exception as exc:
            skipped_candidates.append(f"{key} ({exc.__class__.__name__})")
            continue

        if not _can_enrich_dashboard_output(candidate):
            skipped_candidates.append(f"{key} (missing borrower_id)")
            continue

        source_key = f"s3://{S3_BUCKET_NAME}/{key}"
        df = candidate
        break

    if df.empty:
        try:
            df = _derive_from_cloud_raw_data(s3_client)
            source_key = f"s3://{S3_BUCKET_NAME}/{S3_RAW_PREFIX} (derived)"
        except Exception as exc:
            detail = ", ".join(skipped_candidates[:5]) if skipped_candidates else "no readable CSV candidates"
            raise FileNotFoundError(
                f"No compatible dashboard CSV found; skipped {detail}. Raw-data fallback failed: {exc.__class__.__name__}: {exc}"
            ) from exc

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
        "paperless_status",
        "web_login_used",
        "mobile_app_downloaded",
        "mobile_app_logged_in",
    }

    missing_required = [field for field in required_fields if field not in df.columns]
    if missing_required:
        borrowers = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_information.csv")
        loans = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}loan_information.csv")
        market = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}market_equity.csv")
        engagement = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}borrower_engagement.csv")
        
        # Load account health status if needed
        try:
            account_health = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}account_health_status.csv")
            # Rename custid to borrower_id for merging
            account_health = account_health.rename(columns={"custid": "borrower_id"})
            account_health["borrower_id"] = account_health["borrower_id"].map(_normalize_borrower_id)
        except Exception:
            account_health = None

        enriched = borrowers.merge(loans, on=["borrower_id", "property_id"], how="inner")
        enriched = enriched.merge(market, on="property_id", how="inner")
        enriched = enriched.merge(engagement, on="borrower_id", how="inner")
        enriched["borrower_id"] = enriched["borrower_id"].map(_normalize_borrower_id)
        
        # Merge account health status if available
        if account_health is not None:
            enriched = enriched.merge(
                account_health[["borrower_id", "paperless_status", "web_login_used", "mobile_app_downloaded", "mobile_app_logged_in"]],
                on="borrower_id",
                how="left"
            )
        
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
            "paperless_status",
            "web_login_used",
            "mobile_app_downloaded",
            "mobile_app_logged_in",
        ]
        if "borrower_id" in df.columns:
            df["borrower_id"] = df["borrower_id"].map(_normalize_borrower_id)
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
    if "paperless_status" not in df.columns:
        df["paperless_status"] = "N/A"
    if "web_login_used" not in df.columns:
        df["web_login_used"] = False
    if "mobile_app_downloaded" not in df.columns:
        df["mobile_app_downloaded"] = False
    if "mobile_app_logged_in" not in df.columns:
        df["mobile_app_logged_in"] = False

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
    
    # Load account health status
    try:
        account_health = _read_s3_csv(s3_client, f"{S3_RAW_PREFIX}account_health_status.csv")
        account_health = account_health.rename(columns={"custid": "borrower_id"})
        account_health["borrower_id"] = account_health["borrower_id"].map(_normalize_borrower_id)
    except Exception:
        account_health = None

    df = borrowers.merge(loans, on=["borrower_id", "property_id"], how="inner")
    df = df.merge(market, on="property_id", how="inner")
    df = df.merge(engagement, on="borrower_id", how="inner")
    df["borrower_id"] = df["borrower_id"].map(_normalize_borrower_id)
    
    # Merge account health status if available
    if account_health is not None:
        df = df.merge(
            account_health[["borrower_id", "paperless_status", "web_login_used", "mobile_app_downloaded", "mobile_app_logged_in"]],
            on="borrower_id",
            how="left"
        )
    
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
        "web_login_used",
        "mobile_app_downloaded",
        "mobile_app_logged_in",
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


def build_payload(df: pd.DataFrame, source_key: str | None) -> dict[str, Any]:
    # Define required columns
    required_columns = [
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
        "paperless_status",
        "web_login_used",
        "mobile_app_downloaded",
        "mobile_app_logged_in",
    ]
    
    # Only select columns that exist in the dataframe
    available_columns = [col for col in required_columns if col in df.columns]
    records = df[available_columns].to_dict(orient="records")

    def _json_safe_value(key: str, value: Any) -> Any:
        if pd.isna(value):
            if key in {
                "paperless_billing",
                "email_open_last_30d",
                "mobile_app_login_last_30d",
                "sms_opt_in",
                "web_login_used",
                "mobile_app_downloaded",
                "mobile_app_logged_in",
            }:
                return False
            if key == "paperless_status":
                return ""
            return None
        return value

    for record in records:
        for key, value in list(record.items()):
            record[key] = _json_safe_value(str(key), value)

        # Safely round numeric fields if they exist
        if "current_interest_rate" in record and record["current_interest_rate"] is not None:
            record["current_interest_rate"] = round(float(record["current_interest_rate"]), 2)
        if "market_rate_offer" in record and record["market_rate_offer"] is not None:
            record["market_rate_offer"] = round(float(record["market_rate_offer"]), 2)
        if "monthly_savings_est" in record and record["monthly_savings_est"] is not None:
            record["monthly_savings_est"] = round(float(record["monthly_savings_est"]), 2)
        if "ltv_ratio" in record and record["ltv_ratio"] is not None:
            record["ltv_ratio"] = round(float(record["ltv_ratio"]), 2)
        if "rate_spread" in record and record["rate_spread"] is not None:
            record["rate_spread"] = round(float(record["rate_spread"]), 2)

    categories = ["Immediate Action", "Hot Lead", "Watchlist", "Ineligible"]
    return {
        "records": records,
        "categories": categories,
        "source_key": source_key,
        "s3_path": source_key,
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
                f"Cloud pipeline output unavailable. Expected latest CSV in "
                f"s3://{S3_BUCKET_NAME}/output/ or output/athena/. "
                f"Error: {exc.__class__.__name__}: {exc}"
            ),
        ) from exc
    payload = build_payload(df, source_key)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "data_json": json.dumps(payload, allow_nan=False),
        },
    )


class PipelineRunRequest(BaseModel):
    # mirror the dashboard query parameters so callers can drive the pipeline
    category: list[str] | None = None
    ltv_min: float | None = None
    ltv_max: float | None = None
    spread_min: float | None = None
    spread_max: float | None = None
    email_active: bool | None = None
    mobile_active: bool | None = None
    paperless_enrolled: bool | None = None
    sms_opted_in: bool | None = None
    # optional raw SQL overrides
    qualification_query: str | None = None
    view_query: str | None = None


class AthenaPromptRequest(BaseModel):
    prompt: str


class BedrockAgentQueryRequest(BaseModel):
    question: str
    max_iterations: int | None = None
    run_on_athena: bool = False


def _safe_float(value: Any, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _sanitize_prompt_filters(raw: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}

    categories = raw.get("category")
    if isinstance(categories, str):
        categories = [categories]
    if isinstance(categories, list):
        clean_categories: list[str] = []
        for item in categories:
            if isinstance(item, str) and item not in clean_categories:
                clean_categories.append(item)
        if clean_categories:
            output["category"] = clean_categories

    ltv_min = _safe_float(raw.get("ltv_min"), 0.0, 999.0)
    ltv_max = _safe_float(raw.get("ltv_max"), 0.0, 999.0)
    if ltv_min is not None and ltv_max is not None and ltv_min > ltv_max:
        ltv_min, ltv_max = ltv_max, ltv_min
    if ltv_min is not None:
        output["ltv_min"] = ltv_min
    if ltv_max is not None:
        output["ltv_max"] = ltv_max

    spread_min = _safe_float(raw.get("spread_min"), -100.0, 100.0)
    spread_max = _safe_float(raw.get("spread_max"), -100.0, 100.0)
    if spread_min is not None and spread_max is not None and spread_min > spread_max:
        spread_min, spread_max = spread_max, spread_min
    if spread_min is not None:
        output["spread_min"] = spread_min
    if spread_max is not None:
        output["spread_max"] = spread_max

    return output


def _filters_from_prompt(prompt: str) -> dict[str, Any]:
    client = _get_openai_client()

    system_prompt = (
        "Extract dashboard filter values from user text. "
        "Return JSON with keys: category, ltv_min, ltv_max, spread_min, spread_max. "
        "If a value is not mentioned, set it to null. "
        "Interpret natural language descriptions of criteria as filter ranges."
    )

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )

    content = completion.choices[0].message.content if completion.choices else "{}"
    parsed = _parse_json_object(content)

    return _sanitize_prompt_filters(parsed)


@app.post("/api/athena/agent-query")
def generate_athena_query_from_prompt(req: AthenaPromptRequest) -> dict[str, Any]:
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    filters = _filters_from_prompt(prompt)
    qualification_query = _qualification_sql_from_prompt(prompt)

    return {
        "model": "gpt-4o-mini",
        "filters": filters,
        "qualification_query": qualification_query,
    }


pipeline_run_args: list[str] = []


@app.post("/api/pipeline/run")
def run_pipeline(req: PipelineRunRequest | None = None) -> dict[str, Any]:
    """Trigger pipeline execution.  The request body may include any of the
    same filtering options supported by ``/api/data``; these values are
    translated into CLI arguments that the underlying ``run_pipeline.py``
    script understands.  Additionally whole-query overrides can be supplied
    via ``qualification_query`` or ``view_query``.

    Example JSON body::

        {
            "ltv_max": 75,
            "spread_min": 1.25,
            "qualification_query": "SELECT ..."
        }
    """
    if not PIPELINE_SCRIPT.exists():
        raise HTTPException(status_code=404, detail=f"Pipeline script not found: {PIPELINE_SCRIPT}")

    # convert request into CLI tokens
    global pipeline_run_args
    pipeline_run_args = []
    if req is not None:
        if req.view_query:
            # write override to a temporary file and pass path
            import tempfile
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".sql", mode="w")
            tf.write(req.view_query)
            tf.close()
            pipeline_run_args.extend(["--view-query-file", tf.name])
        if req.qualification_query:
            import tempfile
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".sql", mode="w")
            tf.write(req.qualification_query)
            tf.close()
            pipeline_run_args.extend(["--qualification-query-file", tf.name])

        # filters
        if req.category:
            for c in req.category:
                pipeline_run_args.extend(["--category", c])
        if req.ltv_min is not None:
            pipeline_run_args.extend(["--ltv-min", str(req.ltv_min)])
        if req.ltv_max is not None:
            pipeline_run_args.extend(["--ltv-max", str(req.ltv_max)])
        if req.spread_min is not None:
            pipeline_run_args.extend(["--spread-min", str(req.spread_min)])
        if req.spread_max is not None:
            pipeline_run_args.extend(["--spread-max", str(req.spread_max)])
        if req.email_active:
            pipeline_run_args.append("--email-active")
        if req.mobile_active:
            pipeline_run_args.append("--mobile-active")
        if req.paperless_enrolled:
            pipeline_run_args.append("--paperless-enrolled")
        if req.sms_opted_in:
            pipeline_run_args.append("--sms-opted-in")

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


@app.get("/api/s3/files")
def list_s3_files() -> dict[str, Any]:
    """List all available CSV files from S3 output locations with metadata."""
    try:
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        csv_objects = _list_generated_output_csv_objects(s3_client)
        
        files = []
        for obj in csv_objects:
            key = obj.get("Key", "")
            last_modified = obj.get("LastModified")
            size = obj.get("Size", 0)
            
            # Determine source type
            source_type = "Pipeline" if key.startswith("output/") and not key.startswith("output/athena/") else "Query"
            
            # Format filename for display
            filename = key.split("/")[-1]
            
            files.append({
                "key": key,
                "filename": filename,
                "last_modified": last_modified.isoformat() if last_modified else None,
                "size": size,
                "size_mb": round(size / (1024 * 1024), 2),
                "source_type": source_type,
                "s3_path": f"s3://{S3_BUCKET_NAME}/{key}"
            })
        
        # Sort by last modified (newest first)
        files.sort(key=lambda x: x["last_modified"] or "", reverse=True)
        
        return {
            "files": files,
            "total": len(files)
        }
    except Exception as e:
        logging.exception("Failed to list S3 files")
        raise HTTPException(status_code=500, detail=f"Failed to list S3 files: {str(e)}")


@app.get("/api/s3/load")
def load_s3_file(key: str) -> dict[str, Any]:
    """Load a specific CSV file from S3 and return dashboard data."""
    try:
        logging.info(f"Loading S3 file: {key}")
        s3_client = boto3.client("s3", region_name=AWS_REGION)
        
        # Fetch the CSV from S3
        obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        csv_content = obj["Body"].read()
        
        # Load into pandas
        df = pd.read_csv(BytesIO(csv_content))
        logging.info(f"Loaded CSV with {len(df)} rows and columns: {df.columns.tolist()}")
        
        # Apply marketing categorization if needed
        if "marketing_category" not in df.columns and "rate_spread" in df.columns:
            df["marketing_category"] = df["rate_spread"].apply(_categorize_marketing)
            logging.info("Applied marketing categorization")
        
        # Build the payload
        source_type = "Pipeline Output" if key.startswith("output/") and not key.startswith("output/athena/") else "Athena Query"
        s3_path = f"s3://{S3_BUCKET_NAME}/{key}"
        
        payload = build_payload(df, s3_path)
        logging.info(f"Successfully built payload with {len(payload['records'])} records")
        return payload
    except Exception as e:
        logging.exception(f"Failed to load S3 file: {key}")
        raise HTTPException(status_code=500, detail=f"Failed to load file: {str(e)}")


# ---------------------------------------------------------------------------
# Athena-only API
# ---------------------------------------------------------------------------

@app.post("/api/athena/run")
def run_athena(req: PipelineRunRequest | None = None) -> dict[str, Any]:
    """Execute just the Athena queries and return titles.

    The request body accepts the same fields as ``/api/pipeline/run`` but the
    implementation skips data upload, crawlers, and entity resolution.  It's
    useful for rapid iteration when you only need to change query filters.
    A CSV output is written to the same S3 output prefix used by the full
    pipeline; the response includes the S3 path and execution ID.
    """
    try:
        result = _run_athena_only(req)
        return result
    except Exception as e:
        # log full traceback for debugging
        logging.exception("Athena-only run failed")
        # propagate a readable error message back to the client
        detail = str(e) or "internal error"
        raise HTTPException(status_code=500, detail=detail)


@app.get("/api/athena/download")
def download_athena_result(execution_id: str):
    """Stream a previously generated Athena CSV result back to the client.

    The file is read directly from the pipeline output prefix in S3.
    """
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    key = f"{S3_OUTPUT_PREFIX}{execution_id}.csv"
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Result not found: {e}")

    return StreamingResponse(
        obj["Body"],
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=\"{execution_id}.csv\""},
    )


# ---------------------------------------------------------------------------
# Custom query API
# ---------------------------------------------------------------------------

def _to_bool_query(val: Any) -> bool:
    # query parameters are strings, convert to boolean
    if val is None:
        return False
    return _to_bool(val)


def _apply_filters_to_df(
    df: pd.DataFrame,
    categories: list[str] | None,
    ltv_min: float | None,
    ltv_max: float | None,
    spread_min: float | None,
    spread_max: float | None,
    email_active: bool,
    mobile_active: bool,
    paperless_enrolled: bool,
    sms_opted_in: bool,
    web_login_used: bool,
    mobile_app_downloaded: bool,
    mobile_app_logged_in: bool,
) -> pd.DataFrame:
    # apply the same filter logic implemented in the frontend
    records = df

    def _truthy_mask(column_name: str, include_open: bool = False) -> pd.Series:
        if column_name not in records.columns:
            return pd.Series([False] * len(records), index=records.index)
        values = records[column_name].astype(str).str.strip().str.lower()
        truthy = {"true", "1", "yes", "y"}
        if include_open:
            truthy.add("open")
        return values.isin(truthy)

    if categories:
        records = records[records["marketing_category"].isin(categories)]

    if ltv_min is not None or ltv_max is not None:
        if ltv_min is None:
            ltv_min = 0.0
        if ltv_max is None:
            ltv_max = 100.0
        records = records[records["ltv_ratio"].between(ltv_min, ltv_max, inclusive="both")]

    if spread_min is not None or spread_max is not None:
        if spread_min is None:
            spread_min = 0.0
        if spread_max is None:
            spread_max = 3.0
        records = records[records["rate_spread"].between(spread_min, spread_max, inclusive="both")]

    if email_active:
        records = records[_truthy_mask("email_open_last_30d")]
    if mobile_active:
        records = records[_truthy_mask("mobile_app_login_last_30d")]
    if paperless_enrolled:
        if "paperless_status" in records.columns:
            records = records[_truthy_mask("paperless_status", include_open=True)]
        else:
            records = records[_truthy_mask("paperless_billing")]
    if sms_opted_in:
        records = records[_truthy_mask("sms_opt_in")]
    if web_login_used:
        records = records[_truthy_mask("web_login_used")]
    if mobile_app_downloaded:
        records = records[_truthy_mask("mobile_app_downloaded")]
    if mobile_app_logged_in:
        records = records[_truthy_mask("mobile_app_logged_in")]

    return records


@app.get("/api/data")
def query_dashboard(
    category: list[str] | None = None,
    ltv_min: float | None = None,
    ltv_max: float | None = None,
    spread_min: float | None = None,
    spread_max: float | None = None,
    email_active: str | None = None,
    mobile_active: str | None = None,
    paperless_enrolled: str | None = None,
    sms_opted_in: str | None = None,
    web_login_used: str | None = None,
    mobile_app_downloaded: str | None = None,
    mobile_app_logged_in: str | None = None,
) -> dict[str, Any]:
    """Return a payload similar to the root dashboard but filtered according to query parameters.

    All parameters are optional. ``category`` may be provided multiple times
    (e.g. ``?category=Hot+Lead&category=Watchlist``) and is treated as an
    inclusive list. Boolean flags expect truthy values (``true``, ``1``,
    ``yes`` etc)."""
    df = load_dashboard_dataframe()
    filtered = _apply_filters_to_df(
        df,
        categories=category,
        ltv_min=ltv_min,
        ltv_max=ltv_max,
        spread_min=spread_min,
        spread_max=spread_max,
        email_active=_to_bool_query(email_active),
        mobile_active=_to_bool_query(mobile_active),
        paperless_enrolled=_to_bool_query(paperless_enrolled),
        sms_opted_in=_to_bool_query(sms_opted_in),
        web_login_used=_to_bool_query(web_login_used),
        mobile_app_downloaded=_to_bool_query(mobile_app_downloaded),
        mobile_app_logged_in=_to_bool_query(mobile_app_logged_in),
    )

    source = None
    try:
        # reuse existing loader to obtain source_key
        _, source = load_dashboard_data()
    except Exception:
        source = None

    return build_payload(filtered, source)


# ---------------------------------------------------------------------------
# Bedrock + LangChain NL-to-SQL agentic endpoint
# ---------------------------------------------------------------------------

@app.get("/api/schema")
def get_schema() -> dict[str, Any]:
    """Return the database schema context used by the NL-to-SQL agent.

    Useful for debugging or for building custom frontend prompts.
    """
    from app.nl2sql_agent import build_schema_context, _load_table_schemas  # noqa: PLC0415

    return {
        "schema_context": build_schema_context(),
        "tables": _load_table_schemas(),
    }


@app.post("/api/athena/agent-query-v2")
def bedrock_agent_query(req: BedrockAgentQueryRequest) -> dict[str, Any]:
    """Agentic NL-to-SQL endpoint backed by AWS Bedrock (Claude) + LangChain.

    Implements an **Answerability → Generate → Critique → Execute → Refine** loop:
      0. Answerability – a pre-flight LLM call checks whether the question can
                          be answered from the available schema.  If not, the
                          response contains ``answerability.answerable=false``,
                          a plain-English ``reasoning`` and a ``missing_data``
                          list — no SQL is generated.
      1. Generator  – Claude drafts an Athena SQL query from the natural-language
                      question, embedding full table schema context.
      2. Critic     – a second Claude call reviews the SQL for schema correctness,
                      Athena/Presto syntax, and whether it answers the question.
      3. Executor   – the SQL is executed against Athena; errors are fed back.
      4. Refiner    – if the critic or Athena flagged issues the generator
                      rewrites the SQL with all feedback embedded in the prompt.
      Steps 2-4 repeat up to ``max_iterations`` times (default 3).

    Request body:
      ``question``        – natural-language question (required).
      ``max_iterations``  – override the default iteration cap (optional, 1-5).
      ``run_on_athena``   – if true, execute the final approved SQL on Athena and
                            return the S3 result path (optional, default false).

    Response includes the final SQL, ``answerability`` object (answerable,
    reasoning, missing_data), per-iteration trace, model used, and whether the
    critic approved the query.

    Falls back automatically to OpenAI GPT-4o when Bedrock is unavailable.
    """
    from app.nl2sql_agent import run_nl2sql_agent  # noqa: PLC0415

    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required.")

    max_iter = req.max_iterations
    if max_iter is not None:
        max_iter = max(1, min(5, max_iter))

    try:
        if max_iter is not None:
            from app.nl2sql_agent import run_bedrock_nl2sql_agent, run_nl2sql_agent as _run  # noqa: PLC0415

            try:
                from app.nl2sql_agent import run_bedrock_nl2sql_agent  # noqa: PLC0415
                result = run_bedrock_nl2sql_agent(question, max_iterations=max_iter)
            except Exception:
                result = _run(question)
        else:
            result = run_nl2sql_agent(question)
    except Exception as exc:
        logging.exception("Bedrock NL2SQL agent error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, Any] = result.to_dict()

    # Optionally execute the generated SQL on Athena
    if req.run_on_athena and result.sql:
        if not _is_valid_qualification_sql(result.sql):
            response["athena_error"] = "Generated SQL did not pass safety check."
        else:
            try:
                athena_client = boto3.client("athena", region_name=AWS_REGION)
                qid = execute_athena_query(
                    athena_client,
                    result.sql,
                    GLUE_DATABASE_NAME,
                    FINAL_OUTPUT_LOCATION,
                )
                response["query_execution_id"] = qid
                response["s3_path"] = f"{FINAL_OUTPUT_LOCATION}{qid}.csv"
            except Exception as exc:
                response["athena_error"] = str(exc)

    return response
