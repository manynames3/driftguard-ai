import json

import lambda_function


def api_event(body, headers=None):
    return {
        "headers": headers or {"origin": "https://driftguard-ai.pages.dev"},
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps(body),
    }


def parse_response(response):
    return response["statusCode"], json.loads(response["body"])


def test_lambda_rejects_unknown_scenario():
    status_code, payload = parse_response(
        lambda_function.handler(api_event({"scenario": "iam"}), None)
    )

    assert status_code == 400
    assert payload["allowed_scenarios"] == ["rds", "s3", "security-group"]


def test_lambda_rejects_public_pr_creation_without_admin_key(monkeypatch):
    monkeypatch.delenv("DEMO_ADMIN_KEY", raising=False)
    monkeypatch.delenv("DEMO_ADMIN_KEY_PARAMETER_NAME", raising=False)

    status_code, payload = parse_response(
        lambda_function.handler(api_event({"scenario": "s3", "create_pr": True}), None)
    )

    assert status_code == 403
    assert "dry-run only" in payload["error"]


def test_lambda_returns_stable_payload_for_fixed_scenario(monkeypatch):
    def fake_run_driftguard(**kwargs):
        assert kwargs["issue_description"].startswith("Security group")
        assert kwargs["dry_run"] is True
        return {
            "triage_category": "security",
            "severity": "critical",
            "triage_reason": "Public SSH exposure.",
            "should_remediate": True,
            "impact_summary": "- Impact",
            "proposed_hcl": "terraform {}",
            "is_valid": True,
            "validation_output": "Success! The configuration is valid.",
            "is_policy_compliant": True,
            "policy_output": "No built-in DriftGuard policy violations detected.",
            "pr_preview_body": "## DriftGuard AI Remediation",
        }

    monkeypatch.setattr(lambda_function, "run_driftguard", fake_run_driftguard)
    monkeypatch.delenv("RUNS_TABLE_NAME", raising=False)

    status_code, payload = parse_response(
        lambda_function.handler(api_event({"scenario": "security-group"}), None)
    )

    assert status_code == 200
    assert payload["mode"] == "lambda-real-terraform-validate"
    assert payload["scenario"]["key"] == "security-group"
    assert payload["terraform"]["is_valid"] is True
    assert payload["pull_request"]["preview_body"].startswith("## DriftGuard")
