"""AWS Lambda API for the low-idle-cost DriftGuard online demo."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from demo_scenarios import DEMO_SCENARIOS, get_demo_scenario
from driftguard import DriftGuardState, run_driftguard


DEFAULT_ALLOWED_ORIGIN = "https://driftguard-ai.pages.dev"
MAX_RESPONSE_TEXT_LENGTH = 14000

_ssm_cache: Dict[str, str] = {}


def _json_response(
    status_code: int,
    payload: Dict[str, Any],
    event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return an API Gateway HTTP API response with strict CORS headers."""

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": _allowed_origin(event or {}),
            "Access-Control-Allow-Headers": "content-type,x-driftguard-demo-key",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Vary": "Origin",
        },
        "body": json.dumps(payload, default=str),
    }


def _allowed_origin(event: Dict[str, Any]) -> str:
    """Allow the configured Pages origin, local development, or '*' when requested."""

    configured = os.getenv("CORS_ALLOWED_ORIGIN", DEFAULT_ALLOWED_ORIGIN).strip()
    if configured == "*":
        return "*"

    headers = _headers(event)
    request_origin = headers.get("origin", "")
    allowed = {origin.strip() for origin in configured.split(",") if origin.strip()}
    allowed.update({"http://127.0.0.1:4176", "http://localhost:4176"})

    if request_origin in allowed:
        return request_origin
    return next(iter(allowed), DEFAULT_ALLOWED_ORIGIN)


def _headers(event: Dict[str, Any]) -> Dict[str, str]:
    """Normalize API Gateway headers to lowercase keys."""

    raw_headers = event.get("headers") or {}
    return {str(key).lower(): str(value) for key, value in raw_headers.items()}


def _request_method(event: Dict[str, Any]) -> str:
    """Read the HTTP method from API Gateway v2 or local test events."""

    return (
        event.get("requestContext", {})
        .get("http", {})
        .get("method", event.get("httpMethod", "POST"))
        .upper()
    )


def _parse_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse and validate the JSON body sent by the static demo frontend."""

    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Request body must be valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object.")
    return parsed


def _get_ssm_parameter(name: str) -> str:
    """Read a standard or SecureString SSM parameter with in-process caching."""

    if not name:
        return ""
    if name in _ssm_cache:
        return _ssm_cache[name]

    import boto3

    value = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"][
        "Value"
    ]
    _ssm_cache[name] = value
    return value


def _secret_from_env_or_parameter(value_env: str, parameter_env: str) -> str:
    """Resolve config from an env var first, then an SSM parameter name."""

    direct_value = os.getenv(value_env, "").strip()
    if direct_value:
        return direct_value

    parameter_name = os.getenv(parameter_env, "").strip()
    if not parameter_name:
        return ""
    return _get_ssm_parameter(parameter_name)


def _is_admin_request(event: Dict[str, Any]) -> bool:
    """Check the optional demo admin key used for sandbox PR creation."""

    try:
        expected_key = _secret_from_env_or_parameter(
            "DEMO_ADMIN_KEY",
            "DEMO_ADMIN_KEY_PARAMETER_NAME",
        )
    except Exception:
        return False

    supplied_key = _headers(event).get("x-driftguard-demo-key", "")
    return bool(expected_key and supplied_key and supplied_key == expected_key)


def _configure_optional_github_auth() -> None:
    """Load GitHub token from SSM only when admin PR creation is requested."""

    try:
        github_token = _secret_from_env_or_parameter(
            "GITHUB_TOKEN",
            "GITHUB_TOKEN_PARAMETER_NAME",
        )
    except Exception:
        github_token = ""

    if github_token:
        os.environ["GITHUB_TOKEN"] = github_token


def _trim_text(value: Any, limit: int = MAX_RESPONSE_TEXT_LENGTH) -> str:
    """Keep API responses and DynamoDB run records below practical size limits."""

    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated]"


def _state_to_api_response(
    run_id: str,
    scenario_key: str,
    state: DriftGuardState,
    duration_ms: int,
) -> Dict[str, Any]:
    """Project internal graph state into a stable frontend API response."""

    scenario = get_demo_scenario(scenario_key)
    pr_url = state.get("pr_url", "")
    pr_preview = state.get("pr_preview_body", "")
    pr_error = state.get("pr_error", "")

    if pr_url:
        status = "sandbox_pr_opened"
    elif state.get("is_valid") and state.get("is_policy_compliant") and pr_preview:
        status = "dry_run_ready"
    else:
        status = "blocked"

    return {
        "run_id": run_id,
        "mode": "lambda-real-terraform-validate",
        "status": status,
        "duration_ms": duration_ms,
        "scenario": {
            "key": scenario_key,
            "label": scenario["label"],
            "title": scenario["title"],
            "description": scenario["description"],
        },
        "triage": {
            "category": state.get("triage_category", "unknown"),
            "severity": state.get("severity", "unknown"),
            "reason": state.get("triage_reason", ""),
            "should_remediate": state.get("should_remediate", False),
        },
        "impact_summary": _trim_text(state.get("impact_summary", "")),
        "terraform": {
            "hcl": _trim_text(state.get("proposed_hcl", "")),
            "is_valid": state.get("is_valid", False),
            "validation_output": _trim_text(state.get("validation_output", "")),
            "validation_errors": _trim_text(state.get("validation_errors", "")),
            "init_stdout": _trim_text(state.get("terraform_init_stdout", "")),
            "init_stderr": _trim_text(state.get("terraform_init_stderr", "")),
            "validate_stdout": _trim_text(state.get("terraform_validate_stdout", "")),
            "validate_stderr": _trim_text(state.get("terraform_validate_stderr", "")),
        },
        "policy": {
            "is_compliant": state.get("is_policy_compliant", False),
            "output": _trim_text(state.get("policy_output", "")),
            "errors": _trim_text(state.get("policy_errors", "")),
        },
        "pull_request": {
            "created": bool(pr_url),
            "url": pr_url,
            "branch": state.get("pr_branch", ""),
            "preview_body": _trim_text(pr_preview),
            "error": _trim_text(pr_error),
        },
        "safety": {
            "auto_apply": False,
            "fixed_scenario_only": True,
            "llm_mode": "mock-fixed-output",
        },
    }


def _store_run_record(response_payload: Dict[str, Any]) -> None:
    """Persist a compact run record when RUNS_TABLE_NAME is configured."""

    table_name = os.getenv("RUNS_TABLE_NAME", "").strip()
    if not table_name:
        return

    import boto3

    now = int(time.time())
    item = {
        "run_id": response_payload["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ttl": now + int(os.getenv("RUN_RECORD_TTL_SECONDS", "2592000")),
        "scenario_key": response_payload["scenario"]["key"],
        "status": response_payload["status"],
        "duration_ms": response_payload["duration_ms"],
        "is_valid": response_payload["terraform"]["is_valid"],
        "is_policy_compliant": response_payload["policy"]["is_compliant"],
        "pr_url": response_payload["pull_request"]["url"],
        "validation_errors": _trim_text(response_payload["terraform"]["validation_errors"], 2000),
    }
    boto3.resource("dynamodb").Table(table_name).put_item(Item=item)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda handler for POST /api/demo/run."""

    if _request_method(event) == "OPTIONS":
        return _json_response(204, {}, event)

    try:
        body = _parse_json_body(event)
    except ValueError as exc:
        return _json_response(400, {"error": str(exc)}, event)

    scenario_key = str(body.get("scenario", "s3")).strip()
    if scenario_key not in DEMO_SCENARIOS:
        return _json_response(
            400,
            {
                "error": "Unsupported demo scenario.",
                "allowed_scenarios": sorted(DEMO_SCENARIOS),
            },
            event,
        )

    create_pr = bool(body.get("create_pr", False))
    if create_pr and not _is_admin_request(event):
        return _json_response(
            403,
            {
                "error": (
                    "Sandbox PR creation requires x-driftguard-demo-key. "
                    "Public demo requests are dry-run only."
                )
            },
            event,
        )

    if create_pr:
        _configure_optional_github_auth()

    scenario = get_demo_scenario(scenario_key)
    run_id = uuid.uuid4().hex
    started = time.monotonic()

    os.environ["DRIFTGUARD_MOCK_LLM"] = "true"
    os.environ.setdefault("TERRAFORM_INIT_TIMEOUT_SECONDS", "45")
    os.environ.setdefault("TERRAFORM_VALIDATE_TIMEOUT_SECONDS", "30")

    try:
        state = run_driftguard(
            issue_description=scenario["issue_description"],
            aws_event=scenario["aws_event"],
            max_correction_attempts=int(os.getenv("DEMO_MAX_CORRECTION_ATTEMPTS", "1")),
            dry_run=not create_pr,
        )
    except Exception as exc:
        return _json_response(
            500,
            {
                "run_id": run_id,
                "error": "DriftGuard backend run failed before producing a final state.",
                "detail": _trim_text(exc),
            },
            event,
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    response_payload = _state_to_api_response(run_id, scenario_key, state, duration_ms)

    try:
        _store_run_record(response_payload)
    except Exception as exc:
        response_payload["run_history_warning"] = _trim_text(exc, 1000)

    return _json_response(200, response_payload, event)
