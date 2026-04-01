"""nl2sql_agent.py – Bedrock + LangChain powered Natural-Language-to-SQL agent.

Architecture (Answerability → Generate → Critique → Execute → Refine loop):
  0. AnswerabilityGate – before generating any SQL, the LLM is asked whether
                          the question can be answered from the available schema.
                          If not, a clear reasoning + missing_data list is
                          returned immediately (no SQL generated).
  1. SchemaLoader    – reads CSV schemas and describes the Athena view/tables.
  2. GeneratorChain  – Claude (via Bedrock) drafts an Athena/Presto SQL query.
  3. CriticChain     – a second Claude call reviews the SQL against the schema
                       and returns a structured critique (issues + suggestions).
  4. AthenExecutor   – the generated SQL is actually run against Athena; any
                       execution error (e.g. wrong column name, type mismatch)
                       is captured and fed back into the next refine iteration.
  5. RefinerChain    – if the critic found issues OR Athena returned an error,
                       Claude rewrites the SQL with all feedback embedded in
                       the prompt.
  6. The loop repeats until both the critic approves AND Athena executes
     successfully, or max_iterations is reached.

Fallback: if Bedrock credentials / model access are unavailable the agent
falls back to the OpenAI GPT-4o-mini implementation that already exists in
main.py.  The answerability gate also runs via OpenAI in that path.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

# Default Bedrock model – Amazon Nova Pro (converse API, no use-case form required).
# Set BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0 to use Claude once
# the Anthropic use-case form is submitted in the AWS Bedrock console.
DEFAULT_BEDROCK_MODEL = os.getenv(
    "BEDROCK_MODEL_ID",
    "amazon.nova-pro-v1:0",
)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Athena execution settings for the feedback loop.
_ATHENA_DATABASE = os.getenv("GLUE_DATABASE_NAME", "refi_ready_db")
_S3_BUCKET = os.getenv("REFI_S3_BUCKET", "refi-ready-poc-dev")
_ATHENA_OUTPUT_LOCATION = os.getenv(
    "ATHENA_OUTPUT_LOCATION",
    f"s3://{_S3_BUCKET}/athena-results/nl2sql/",
)
# Max seconds to wait for a feedback-loop execution before giving up.
_ATHENA_EXEC_TIMEOUT_S = int(os.getenv("NL2SQL_ATHENA_TIMEOUT", "60"))

# The maximum number of Generate → Critique → Execute → Refine iterations.
MAX_AGENT_ITERATIONS = int(os.getenv("NL2SQL_MAX_ITERATIONS", "3"))

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_DATA_FILES = [
    "borrower_information.csv",
    "loan_information.csv",
    "market_equity.csv",
    "borrower_engagement.csv",
    "account_health_status.csv",
]

# Maps CSV filename → Athena/Glue table name.
_ATHENA_TABLE_NAMES: dict[str, str] = {
    "borrower_information.csv": "borrower_information_csv",
    "loan_information.csv": "loan_information_csv",
    "market_equity.csv": "market_equity_csv",
    "borrower_engagement.csv": "borrower_engagement_csv",
    "account_health_status.csv": "account_health_status_csv",
}

# Prose description of each table to help the model understand domain context.
_TABLE_DESCRIPTIONS: dict[str, str] = {
    "borrower_information_csv": (
        "Core borrower profile: names, contact info, address, credit score, "
        "and property_id used to join loan and market data."
    ),
    "loan_information_csv": (
        "Loan details: original amount, current interest rate, origination year, "
        "loan type (Fixed/ARM), remaining balance, and the borrower_id / property_id "
        "foreign keys."
    ),
    "market_equity_csv": (
        "Property market data: current home value, estimated equity, LTV ratio, "
        "current market rate offer, and estimated monthly savings from refinancing."
    ),
    "borrower_engagement_csv": (
        "Digital engagement flags: paperless billing preference, email opens in the "
        "last 30 days, mobile app login in the last 30 days, SMS opt-in status."
    ),
    "account_health_status_csv": (
        "Account operational status: paperless_status (OPEN/CLOSED/PENDING), "
        "web_login_used, mobile_app_downloaded, mobile_app_logged_in.  "
        "Uses 'custid' as the borrower identifier (maps to borrower_id after normalisation)."
    ),
}

# The pre-built view that joins all four core tables.
_VIEW_DESCRIPTION = """
unified_refi_dataset (VIEW)
  Columns: borrower_id, first_name, last_name,
           current_interest_rate, market_rate_offer, ltv_ratio,
           monthly_savings_est, paperless_billing,
           email_open_last_30d, mobile_app_login_last_30d, sms_opt_in
  This view is the preferred starting point for most refinance-eligibility
  queries.  Use the raw tables only when you need columns not present here
  (e.g. credit_score, city, state, loan_amount, origination_year).
  Join key: borrower_id  (string in all tables).
  NOTE: rate_spread = current_interest_rate - market_rate_offer
  NOTE: marketing_category rules –
        rate_spread > 1.25  → 'Immediate Action'
        rate_spread > 0.75  → 'Hot Lead'
        rate_spread > 0.50  → 'Watchlist'
        else                → 'Ineligible'
  NOTE: boolean-like columns (mobile_app_login_last_30d, email_open_last_30d,
        paperless_billing, sms_opt_in) are VARCHAR in Athena — their values
        are the string literals 'true' or 'false'.  ALWAYS compare them with
        LOWER(col) = 'true'  or  LOWER(col) = 'false'.  NEVER use = true or = false.
"""


def _friendly_dtype(dtype: Any) -> str:
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_bool_dtype(dtype):
        # Athena/Glue reads CSV files as VARCHAR — boolean columns are stored
        # as the string literals 'true' / 'false', NOT as native SQL booleans.
        return "string ('true'/'false')"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    return "string"


@lru_cache(maxsize=1)
def _load_table_schemas() -> dict[str, list[dict[str, str]]]:
    """Return {athena_table_name: [{column, dtype, sample}]} for every CSV."""
    schemas: dict[str, list[dict[str, str]]] = {}
    for fname in _DATA_FILES:
        fpath = DATA_DIR / fname
        if not fpath.exists():
            continue
        try:
            df = pd.read_csv(fpath, nrows=500)
            athena_name = _ATHENA_TABLE_NAMES[fname]
            col_info: list[dict[str, str]] = []
            for col, dtype in df.dtypes.items():
                col_str = str(col)
                samples = df[col_str].dropna().astype(str).head(3).tolist()
                col_info.append(
                    {
                        "column": col_str,
                        "dtype": _friendly_dtype(dtype),
                        "samples": ", ".join(samples),
                    }
                )
            schemas[athena_name] = col_info
        except Exception as exc:
            logger.warning("Could not read schema for %s: %s", fname, exc)
    return schemas


def build_schema_context() -> str:
    """Return a rich schema description suitable for embedding in LLM prompts."""
    schemas = _load_table_schemas()

    lines: list[str] = [
        "=== ATHENA DATABASE: refi_ready_db ===",
        "",
        _VIEW_DESCRIPTION,
        "",
        "=== RAW TABLES ===",
    ]

    for table_name, columns in schemas.items():
        desc = _TABLE_DESCRIPTIONS.get(table_name, "")
        lines.append(f"\nTable: {table_name}")
        if desc:
            lines.append(f"  Description: {desc}")
        lines.append("  Columns:")
        for col in columns:
            lines.append(
                f"    - {col['column']} ({col['dtype']})  e.g. {col['samples']}"
            )

    lines += [
        "",
        "=== QUERY RULES ===",
        "1. Target Athena/Presto SQL syntax.",
        "2. Use the unified_refi_dataset view when sufficient; fall back to raw tables for extra columns.",
        "3. Always qualify column names with table/view alias when joining multiple sources.",
        "4. Boolean-like columns (mobile_app_login_last_30d, email_open_last_30d, paperless_billing, sms_opt_in) are VARCHAR — their values are the strings 'true'/'false'. ALWAYS use LOWER(col) = 'true' or LOWER(col) = 'false'. Never use = true or = false.",
        "5. Do NOT use semicolons at the end of the query.",
        "6. Return only the columns needed to answer the question – avoid SELECT *.",
        "7. For rate_spread calculations use: (current_interest_rate - market_rate_offer).",
        "8. Use CAST(... AS DOUBLE) for numeric operations on columns stored as strings.",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Athena execution  (feedback loop)
# ---------------------------------------------------------------------------

def _try_athena_execution(
    sql: str,
) -> tuple[bool, str | None, list[dict[str, Any]] | None, int | None]:
    """Execute *sql* against Athena and return a (success, error, preview, row_count) tuple.

    A LIMIT-wrapped version of the query is run so the feedback loop never
    fetches large result sets.  The raw query (without LIMIT) is used for
    CREATE/INSERT/DDL statements that cannot be wrapped.

    Returns
    -------
    success : bool
        True when Athena reports SUCCEEDED.
    error : str | None
        The ``StateChangeReason`` from Athena when the query fails, else None.
    preview : list[dict] | None
        Up to 5 data rows as plain dicts when the query succeeded, else None.
    row_count : int | None
        Number of data rows in the preview result (header row excluded), or None.
    """
    # Only wrap SELECT statements with LIMIT to keep previews cheap.
    stripped = sql.strip().upper()
    if stripped.startswith("SELECT") or stripped.startswith("WITH"):
        preview_sql = f"SELECT * FROM ({sql}) _nl2sql_preview LIMIT 5"
    else:
        preview_sql = sql

    try:
        client = boto3.client("athena", region_name=AWS_REGION)
        resp = client.start_query_execution(
            QueryString=preview_sql,
            QueryExecutionContext={"Database": _ATHENA_DATABASE},
            ResultConfiguration={"OutputLocation": _ATHENA_OUTPUT_LOCATION},
        )
        exec_id = resp["QueryExecutionId"]

        deadline = time.monotonic() + _ATHENA_EXEC_TIMEOUT_S
        while True:
            status_resp = client.get_query_execution(QueryExecutionId=exec_id)
            state = status_resp["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            if time.monotonic() > deadline:
                # Cancel the timed-out execution to avoid wasting resources.
                try:
                    client.stop_query_execution(QueryExecutionId=exec_id)
                except Exception:
                    pass
                return False, "Athena execution timed out (feedback loop limit)", None, None
            time.sleep(3)

        if state != "SUCCEEDED":
            reason = (
                status_resp["QueryExecution"]["Status"]
                .get("AthenaError", {})
                .get("ErrorMessage")
                or status_resp["QueryExecution"]["Status"].get("StateChangeReason", "Unknown error")
            )
            return False, reason, None, None

        # Fetch preview rows
        result_resp = client.get_query_results(QueryExecutionId=exec_id, MaxResults=6)
        rows = result_resp.get("ResultSet", {}).get("Rows", [])
        columns = [
            col.get("VarCharValue", f"col{i}")
            for i, col in enumerate(rows[0].get("Data", []))
        ] if rows else []
        data_rows = [
            {columns[i]: cell.get("VarCharValue", "") for i, cell in enumerate(r.get("Data", []))}
            for r in rows[1:]
        ]
        return True, None, data_rows, len(data_rows)

    except Exception as exc:
        logger.warning("Athena feedback-loop execution error: %s", exc)
        return False, str(exc), None, None


# ---------------------------------------------------------------------------
# LangChain / Bedrock chain builders
# ---------------------------------------------------------------------------

def _invoke_bedrock(prompt_messages: list[dict[str, str]], temperature: float = 0.0) -> str:
    """Invoke Bedrock for the configured model.

    Supports two API paths:
    - Anthropic models  → ``invoke_model`` with the Anthropic Messages API body.
    - Amazon Nova / other Converse-compatible models → ``converse`` API.

    Parameters
    ----------
    prompt_messages:
        List of dicts with 'role' ('system' | 'user' | 'assistant') and 'content'.
    temperature:
        Sampling temperature.

    Returns
    -------
    str
        The assistant's text reply.
    """
    runtime = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    model = DEFAULT_BEDROCK_MODEL

    # Split system messages from conversation messages
    system_text = ""
    messages: list[dict[str, Any]] = []
    for msg in prompt_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_text = content
        else:
            messages.append({"role": role, "content": content})

    if model.startswith("anthropic.") or model.startswith("us.anthropic."):
        # Anthropic Messages API via invoke_model
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "temperature": temperature,
            "messages": messages,
        }
        if system_text:
            body["system"] = system_text

        response = runtime.invoke_model(
            modelId=model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]

    else:
        # Amazon Nova / other models via Converse API
        converse_messages = [
            {
                "role": m["role"],
                "content": [{"text": m["content"]}],
            }
            for m in messages
        ]
        kwargs: dict[str, Any] = {
            "modelId": model,
            "messages": converse_messages,
            "inferenceConfig": {"maxTokens": 2048, "temperature": temperature},
        }
        if system_text:
            kwargs["system"] = [{"text": system_text}]

        response = runtime.converse(**kwargs)
        return response["output"]["message"]["content"][0]["text"]


def _build_generator_chain() -> Any:
    """Return a callable that (schema_context, question, critique_block) → SQL str."""
    def _generate(inputs: dict[str, str]) -> str:
        schema_context = inputs["schema_context"]
        question = inputs["question"]
        critique_block = inputs.get("critique_block", "")

        system = (
            "You are an expert Athena/Presto SQL engineer working on a mortgage "
            "refinance analytics platform.  Your job is to convert a natural-language "
            "question into a correct, efficient Athena SQL query.\n\n"
            f"{schema_context}\n\n"
            "Rules:\n"
            "- Return ONLY the raw SQL query text, no markdown fences, no explanation.\n"
            "- Do NOT end the query with a semicolon.\n"
            "- Think step-by-step internally but output only the final SQL.\n"
            f"{critique_block}"
        )

        return _invoke_bedrock(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Question: {question}"},
            ],
            temperature=0.0,
        )

    return type("Chain", (), {"invoke": staticmethod(_generate)})()


def _build_critic_chain() -> Any:
    """Return a callable that (schema_context, question, sql) → critic JSON str."""
    def _critique(inputs: dict[str, str]) -> str:
        schema_context = inputs["schema_context"]
        question = inputs["question"]
        sql = inputs["sql"]

        system = (
            "You are an expert SQL reviewer for an Athena/Presto database.\n\n"
            f"{schema_context}\n\n"
            "Your task: review the given SQL query and return a JSON object with:\n"
            "  - 'approved': true if the query is correct and efficient, false otherwise.\n"
            "  - 'issues': list of specific problems found (empty list if approved).\n"
            "  - 'suggestions': list of actionable improvements (empty list if approved).\n\n"
            "Check for:\n"
            "  1. References to columns that do not exist in the schema.\n"
            "  2. Wrong table/view names.\n"
            "  3. Missing JOIN conditions or Cartesian products.\n"
            "  4. Incorrect data type comparisons (treating 'true'/'false' strings as booleans).\n"
            "  5. Syntax errors for Presto/Athena SQL.\n"
            "  6. Whether the query actually answers the original question.\n"
            "  7. Unnecessary complexity (CTEs when a simple SELECT would suffice).\n\n"
            "Return ONLY valid JSON, no markdown fences."
        )

        human = f"Original question: {question}\n\nSQL to review:\n{sql}"

        return _invoke_bedrock(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": human},
            ],
            temperature=0.0,
        )

    return type("Chain", (), {"invoke": staticmethod(_critique)})()


# ---------------------------------------------------------------------------
# Public agent entry point
# ---------------------------------------------------------------------------

class NL2SQLResult:
    """The result returned by the NL-to-SQL agent."""

    def __init__(
        self,
        sql: str,
        iterations: int,
        trace: list[dict[str, Any]],
        model: str,
        approved: bool,
        execution_ok: bool = False,
        execution_error: str | None = None,
        result_preview: list[dict[str, Any]] | None = None,
        answerability: AnswerabilityResult | None = None,
    ) -> None:
        self.sql = sql
        self.iterations = iterations
        self.trace = trace
        self.model = model
        self.approved = approved
        self.execution_ok = execution_ok
        self.execution_error = execution_error
        self.result_preview = result_preview or []
        self.answerability = answerability

    def to_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "iterations": self.iterations,
            "trace": self.trace,
            "model": self.model,
            "approved": self.approved,
            "execution_ok": self.execution_ok,
            "execution_error": self.execution_error,
            "result_preview": self.result_preview,
            "answerability": self.answerability.to_dict() if self.answerability else None,
        }


def _parse_critic_output(raw: str) -> dict[str, Any]:
    """Extract JSON from the critic's raw text output."""
    # Strip code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find a JSON object anywhere in the output
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                result = {}
        else:
            result = {}
    return result


def _sanitize_sql(raw: str) -> str:
    """Strip markdown fences and trailing semicolons from a generated SQL string."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip().rstrip(";")


# ---------------------------------------------------------------------------
# Answerability gate
# ---------------------------------------------------------------------------

class AnswerabilityResult:
    """Outcome of the pre-flight answerability check."""

    def __init__(
        self,
        answerable: bool,
        reasoning: str,
        missing_data: list[str],
    ) -> None:
        self.answerable = answerable
        self.reasoning = reasoning
        self.missing_data = missing_data

    def to_dict(self) -> dict[str, Any]:
        return {
            "answerable": self.answerable,
            "reasoning": self.reasoning,
            "missing_data": self.missing_data,
        }


def _check_answerability(question: str, schema_context: str) -> AnswerabilityResult:
    """Ask the LLM whether the question can be answered with the available schema.

    Returns an :class:`AnswerabilityResult` with:
    - ``answerable`` – True if a SQL query can fully answer the question.
    - ``reasoning``  – A plain-English explanation of why it can or cannot be
                       answered, including which columns / tables are relevant
                       or which information is absent.
    - ``missing_data`` – List of specific data points / columns that would be
                         needed but are not present in the schema (empty when
                         answerable=True).
    """
    system = (
        "You are a data analyst evaluating whether a natural-language question "
        "can be fully answered by querying the following Athena database schema.\n\n"
        f"{schema_context}\n\n"
        "Respond with ONLY a JSON object (no markdown fences) containing:\n"
        "  \"answerable\": true | false\n"
        "  \"reasoning\": \"<one clear paragraph explaining why the question can or "
        "cannot be answered from the available data — mention specific columns / "
        "tables that are relevant, or explain exactly what data is missing>\",\n"
        "  \"missing_data\": [\"<item1>\", ...]  // empty list when answerable=true\n\n"
        "A question is answerable if every piece of information it requires "
        "exists as a column in one of the available tables or views, either "
        "directly or derivable through standard SQL operations (COUNT, SUM, "
        "JOIN, CASE, etc.).\n"
        "A question is NOT answerable if it requires data that is simply not "
        "present in any table (e.g. transaction history, external credit bureau "
        "data, information about dates not tracked, etc.)."
    )

    try:
        raw = _invoke_bedrock(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Question: {question}"},
            ],
            temperature=0.0,
        )
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except json.JSONDecodeError:
                    pass

        return AnswerabilityResult(
            answerable=bool(parsed.get("answerable", True)),
            reasoning=str(parsed.get("reasoning", "")),
            missing_data=list(parsed.get("missing_data", [])),
        )
    except Exception as exc:
        # If the check itself fails, default to answerable=True to avoid
        # blocking legitimate queries when Bedrock has a transient issue.
        logger.warning("Answerability check failed (%s) – defaulting to answerable=True", exc)
        return AnswerabilityResult(
            answerable=True,
            reasoning="Answerability pre-check could not be completed; proceeding with query generation.",
            missing_data=[],
        )


def run_bedrock_nl2sql_agent(
    question: str,
    max_iterations: int = MAX_AGENT_ITERATIONS,
) -> NL2SQLResult:
    """Run the full Generate → Critique → Execute → Refine agentic loop using AWS Bedrock.

    Parameters
    ----------
    question:
        The natural-language question to convert to SQL.
    max_iterations:
        Maximum number of Generate/Refine attempts before returning the best
        result seen so far regardless of critic approval.

    Returns
    -------
    NL2SQLResult
        Contains the final SQL, per-iteration trace, execution result preview,
        the model used, and whether the critic approved the final output.
    """
    schema_context = build_schema_context()
    trace: list[dict[str, Any]] = []

    # ---- PRE-FLIGHT: can this question be answered from our data? ------------
    answerability = _check_answerability(question, schema_context)
    logger.info(
        "NL2SQL answerability=%s, reasoning=%s",
        answerability.answerable,
        answerability.reasoning,
    )
    if not answerability.answerable:
        return NL2SQLResult(
            sql="",
            iterations=0,
            trace=[],
            model=DEFAULT_BEDROCK_MODEL,
            approved=False,
            answerability=answerability,
        )

    generator_chain = _build_generator_chain()
    critic_chain = _build_critic_chain()

    sql = ""
    critique: dict[str, Any] = {}
    approved = False
    exec_ok = False
    exec_error: str | None = None
    exec_preview: list[dict[str, Any]] | None = None

    for iteration in range(1, max_iterations + 1):
        # ---- GENERATE / REFINE -------------------------------------------------
        feedback_parts: list[str] = []

        if iteration > 1 and critique:
            issues = critique.get("issues", [])
            suggestions = critique.get("suggestions", [])
            if issues:
                feedback_parts.append(
                    "Static analysis issues you MUST fix:\n"
                    + "\n".join(f"  - {i}" for i in issues)
                )
            if suggestions:
                feedback_parts.append(
                    "Suggestions:\n" + "\n".join(f"  - {s}" for s in suggestions)
                )

        if iteration > 1 and exec_error:
            feedback_parts.append(
                f"Athena execution FAILED with this error — you MUST rewrite the SQL to fix it:\n"
                f"  {exec_error}"
            )

        critique_block = ""
        if feedback_parts:
            critique_block = (
                "\nPrevious attempt had problems that you MUST fix:\n"
                + "\n\n".join(feedback_parts)
                + "\n"
            )

        raw_sql = generator_chain.invoke(
            {
                "schema_context": schema_context,
                "question": question,
                "critique_block": critique_block,
            }
        )
        sql = _sanitize_sql(raw_sql)

        # ---- CRITIQUE ----------------------------------------------------------
        raw_critique = critic_chain.invoke(
            {
                "schema_context": schema_context,
                "question": question,
                "sql": sql,
            }
        )
        critique = _parse_critic_output(raw_critique)
        approved = bool(critique.get("approved", False))

        # ---- EXECUTE (feedback loop) ------------------------------------------
        logger.info(
            "NL2SQL iteration %d/%d – critic approved=%s – executing against Athena …",
            iteration,
            max_iterations,
            approved,
        )
        exec_ok, exec_error, exec_preview, exec_row_count = _try_athena_execution(sql)
        logger.info(
            "NL2SQL iteration %d/%d – Athena exec_ok=%s, error=%s, rows=%s",
            iteration,
            max_iterations,
            exec_ok,
            exec_error,
            exec_row_count,
        )

        trace.append(
            {
                "iteration": iteration,
                "sql": sql,
                "approved": approved,
                "issues": critique.get("issues", []),
                "suggestions": critique.get("suggestions", []),
                "execution_ok": exec_ok,
                "execution_error": exec_error,
                "result_preview": exec_preview,
                "row_count": exec_row_count,
            }
        )

        # Stop only when the LLM critic is happy AND Athena ran without error.
        if approved and exec_ok:
            break

        # If the critic approved but Athena failed, mark as not approved so
        # the next iteration picks up the execution error in the feedback block.
        if exec_error:
            approved = False

    return NL2SQLResult(
        sql=sql,
        iterations=len(trace),
        trace=trace,
        model=DEFAULT_BEDROCK_MODEL,
        approved=approved,
        execution_ok=exec_ok,
        execution_error=exec_error,
        result_preview=exec_preview,
        answerability=answerability,
    )


def run_nl2sql_agent(question: str) -> NL2SQLResult:
    """Public entry point.  Tries Bedrock first; falls back to OpenAI on error.

    The OpenAI fallback uses the same schema-aware prompt so quality is
    preserved even when Bedrock is unavailable/unconfigured.
    The answerability gate always runs (via Bedrock or via the fallback path)
    before any SQL is generated.
    """
    try:
        return run_bedrock_nl2sql_agent(question)
    except Exception as bedrock_exc:
        logger.warning(
            "Bedrock NL2SQL agent failed (%s: %s). Falling back to OpenAI.",
            bedrock_exc.__class__.__name__,
            bedrock_exc,
        )
        return _openai_fallback(question, str(bedrock_exc))


# ---------------------------------------------------------------------------
# OpenAI fallback (schema-aware, single-shot, no critic loop)
# ---------------------------------------------------------------------------

def _openai_fallback(question: str, bedrock_error: str) -> NL2SQLResult:
    """Schema-aware OpenAI GPT-4o fallback when Bedrock is unavailable."""
    import importlib

    try:
        openai_module = importlib.import_module("openai")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"Bedrock unavailable ({bedrock_error}) and OpenAI SDK is not installed."
        ) from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            f"Bedrock unavailable ({bedrock_error}) and OPENAI_API_KEY is not set."
        )

    client = openai_module.OpenAI(api_key=api_key)
    schema_context = build_schema_context()

    # ---- Answerability gate (OpenAI path) ------------------------------------
    answerability = _check_answerability_openai(client, question, schema_context)
    logger.info(
        "NL2SQL (OpenAI fallback) answerability=%s", answerability.answerable
    )
    if not answerability.answerable:
        return NL2SQLResult(
            sql="",
            iterations=0,
            trace=[],
            model="gpt-4o (fallback)",
            approved=False,
            answerability=answerability,
        )

    system_prompt = (
        "You are an Athena/Presto SQL expert.  Convert the user's question into "
        "a correct SQL query.  Return ONLY the raw SQL (no markdown, no explanation).\n\n"
        f"{schema_context}"
    )

    completion = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
    )

    raw = completion.choices[0].message.content if completion.choices else ""
    sql = _sanitize_sql(raw or "")

    return NL2SQLResult(
        sql=sql,
        iterations=1,
        trace=[
            {
                "iteration": 1,
                "sql": sql,
                "approved": True,
                "issues": [],
                "suggestions": [],
                "note": f"OpenAI fallback (Bedrock error: {bedrock_error})",
            }
        ],
        model="gpt-4o (fallback)",
        approved=True,
        answerability=answerability,
    )


def _check_answerability_openai(
    client: Any,
    question: str,
    schema_context: str,
) -> AnswerabilityResult:
    """Run the answerability check via OpenAI when Bedrock is unavailable."""
    system = (
        "You are a data analyst evaluating whether a natural-language question "
        "can be fully answered by querying the following Athena database schema.\n\n"
        f"{schema_context}\n\n"
        "Respond with ONLY a JSON object (no markdown fences) containing:\n"
        "  \"answerable\": true | false\n"
        "  \"reasoning\": \"<plain-English explanation>\",\n"
        "  \"missing_data\": [\"<item>\", ...]  // empty when answerable=true"
    )
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Question: {question}"},
            ],
        )
        raw = completion.choices[0].message.content if completion.choices else "{}"
        cleaned = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except json.JSONDecodeError:
                    pass
        return AnswerabilityResult(
            answerable=bool(parsed.get("answerable", True)),
            reasoning=str(parsed.get("reasoning", "")),
            missing_data=list(parsed.get("missing_data", [])),
        )
    except Exception as exc:
        logger.warning("OpenAI answerability check failed (%s) – defaulting to answerable=True", exc)
        return AnswerabilityResult(
            answerable=True,
            reasoning="Answerability pre-check could not be completed; proceeding with query generation.",
            missing_data=[],
        )
