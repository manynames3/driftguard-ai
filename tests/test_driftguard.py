import shutil
from argparse import Namespace

import pytest

import driftguard
from driftguard import (
    build_pull_request_body,
    collect_policy_violations,
    format_run_summary,
    mock_structured_response,
    policy_check_node,
    pull_request_node,
    redact_sensitive_data,
    redact_string,
    TerraformRemediation,
    validate_cli_prerequisites,
    validate_node,
)


def test_redact_string_removes_account_ids_and_access_keys():
    value = "account 123456789012 used access key AKIA1234567890ABCDEF token=secret-value"

    redacted = redact_string(value)

    assert "123456789012" not in redacted
    assert "AKIA1234567890ABCDEF" not in redacted
    assert "secret-value" not in redacted


def test_redact_sensitive_data_redacts_sensitive_keys_recursively():
    event = {
        "account": "123456789012",
        "detail": {
            "sessionToken": "should-not-leak",
            "safe": "bucket 123456789012",
        },
    }

    redacted = redact_sensitive_data(event)

    assert redacted["account"] == "[AWS_ACCOUNT_ID]"
    assert redacted["detail"]["sessionToken"] == "[REDACTED]"
    assert redacted["detail"]["safe"] == "bucket [AWS_ACCOUNT_ID]"


def test_policy_scan_blocks_obvious_public_ssh():
    hcl = """
    resource "aws_security_group_rule" "bad" {
      type        = "ingress"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
    """

    violations = collect_policy_violations(hcl)

    assert violations == ["Inbound SSH/RDP from 0.0.0.0/0 is not allowed."]


def test_policy_check_passes_safe_public_access_block():
    state = {
        "is_valid": True,
        "proposed_hcl": """
        resource "aws_s3_bucket_public_access_block" "safe" {
          bucket                  = "example"
          block_public_acls       = true
          block_public_policy     = true
          ignore_public_acls      = true
          restrict_public_buckets = true
        }
        """,
    }

    result = policy_check_node(state)

    assert result["is_policy_compliant"] is True
    assert result["policy_errors"] == ""


def test_policy_check_feeds_errors_back_into_correction_loop():
    state = {
        "is_valid": True,
        "correction_attempts": 0,
        "proposed_hcl": 'resource "aws_s3_bucket" "bad" { acl = "public-read" }',
    }

    result = policy_check_node(state)

    assert result["is_valid"] is False
    assert result["is_policy_compliant"] is False
    assert "Policy check failed" in result["validation_errors"]
    assert result["correction_attempts"] == 1


def test_pull_request_node_dry_run_returns_preview_without_github_import():
    state = {
        "dry_run": True,
        "is_valid": True,
        "is_policy_compliant": True,
        "impact_summary": "- Security risk reduced.",
        "reason_for_fix": "Adds explicit Terraform control.",
        "validation_output": "Success! The configuration is valid.",
        "policy_output": "No built-in DriftGuard policy violations detected.",
        "proposed_hcl": "terraform {}",
    }

    result = pull_request_node(state)

    assert result["pr_error"] == ""
    assert "DriftGuard AI Remediation" in result["pr_preview_body"]
    assert "Terraform Validate" in result["pr_preview_body"]


def test_pull_request_node_blocks_without_policy_pass():
    result = pull_request_node({"dry_run": True, "is_valid": True})

    assert "policy checks did not pass" in result["pr_error"]


def test_pull_request_node_blocks_upstream_llm_error():
    result = pull_request_node(
        {
            "dry_run": True,
            "is_valid": True,
            "is_policy_compliant": True,
            "llm_error": "Impact analysis LLM failure",
        }
    )

    assert "upstream LLM step failed" in result["pr_error"]


def test_build_pull_request_body_includes_policy_check():
    body = build_pull_request_body(
        {
            "impact_summary": "- Impact",
            "reason_for_fix": "Reason",
            "validation_output": "Validation passed",
            "policy_output": "Policy passed",
        }
    )

    assert "### Built-In Policy Check" in body
    assert "Policy passed" in body


def test_format_run_summary_includes_pr_preview():
    summary = format_run_summary(
        {
            "is_valid": True,
            "is_policy_compliant": True,
            "impact_summary": "Impact",
            "reason_for_fix": "Reason",
            "policy_output": "Policy passed",
            "pr_preview_body": "Preview",
        }
    )

    assert "dry-run PR preview ready" in summary
    assert "Preview" in summary


def test_mock_remediation_is_scenario_specific_for_security_group():
    remediation = mock_structured_response(
        TerraformRemediation,
        [("human", "Security group sg-0baddrift allows SSH from 0.0.0.0/0.")],
    )

    assert "aws_security_group" in remediation.terraform_hcl
    assert "approved_admin_cidr" in remediation.terraform_hcl


def test_mock_remediation_is_scenario_specific_for_rds():
    remediation = mock_structured_response(
        TerraformRemediation,
        [("human", "RDS instance orders-prod drifted to db.r6i.2xlarge.")],
    )

    assert "aws_db_instance" in remediation.terraform_hcl
    assert "instance_class" in remediation.terraform_hcl
    assert "db.t3.medium" in remediation.terraform_hcl


def test_validate_cli_prerequisites_allows_mock_dry_run_with_terraform(monkeypatch):
    monkeypatch.setattr(driftguard.shutil, "which", lambda command: "/usr/bin/terraform")
    monkeypatch.delenv("DRIFTGUARD_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    errors = validate_cli_prerequisites(Namespace(mock_llm=True, dry_run=True))

    assert errors == []


def test_validate_cli_prerequisites_reports_missing_real_run_config(monkeypatch):
    monkeypatch.setattr(driftguard.shutil, "which", lambda command: "/usr/bin/terraform")
    monkeypatch.setenv("DRIFTGUARD_LLM_PROVIDER", "openai")
    monkeypatch.delenv("DRIFTGUARD_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    errors = validate_cli_prerequisites(Namespace(mock_llm=False, dry_run=True))

    assert "DRIFTGUARD_LLM_MODEL is required for non-mock runs." in errors
    assert "OPENAI_API_KEY is required when DRIFTGUARD_LLM_PROVIDER=openai." in errors


@pytest.mark.skipif(shutil.which("terraform") is None, reason="Terraform CLI is not installed")
def test_validate_node_runs_real_terraform_validate():
    result = validate_node(
        {
            "proposed_hcl": 'terraform {\n  required_version = ">= 1.0"\n}\n',
            "correction_attempts": 0,
        }
    )

    assert result["is_valid"] is True
    assert result["validation_errors"] == ""
