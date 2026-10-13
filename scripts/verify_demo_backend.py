"""Run fixed scenarios through the Lambda adapter locally, without cloud or PR writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lambda_function import handler


def main() -> int:
    # Keep this opt-in integration check independent of any operator credentials.
    os.environ["DRIFTGUARD_DISABLE_PR_CREATION"] = "true"
    os.environ["RUNS_TABLE_NAME"] = ""
    results = []
    with tempfile.TemporaryDirectory(prefix="driftguard-provider-cache-") as cache:
        os.environ["TF_PLUGIN_CACHE_DIR"] = cache
        for key in ("s3", "security-group", "rds"):
            response = handler({
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"scenario": key, "create_pr": False}),
            }, None)
            payload = json.loads(response["body"])
            terraform = payload.get("terraform", {})
            result = {
                "scenario": key,
                "http_status": response["statusCode"],
                "status": payload.get("status"),
                "terraform_valid": terraform.get("is_valid", False),
                "policy_compliant": payload.get("policy", {}).get("is_compliant", False),
                "preview_prepared": bool(payload.get("pull_request", {}).get("preview_body")),
                "pr_created": payload.get("pull_request", {}).get("created", False),
                "validation_stdout": terraform.get("validate_stdout", ""),
                "errors": terraform.get("validation_errors", "") or payload.get("error", ""),
            }
            results.append(result)
            print(json.dumps(result), flush=True)
    return 0 if all(
        result["http_status"] == 200 and result["terraform_valid"] and
        result["policy_compliant"] and result["preview_prepared"] and not result["pr_created"]
        for result in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
