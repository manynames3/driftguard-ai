"""
DriftGuard AI

Event-driven LangGraph workflow for detecting AWS infrastructure drift, drafting
Terraform remediation, validating the generated HCL in a real sandbox, and
opening a GitHub pull request with the validated fix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Optional, Type, TypedDict

from pydantic import BaseModel, Field


DEFAULT_MAX_CORRECTION_ATTEMPTS = 3
DEFAULT_TERRAFORM_INIT_TIMEOUT_SECONDS = 120
DEFAULT_TERRAFORM_VALIDATE_TIMEOUT_SECONDS = 60


class DriftGuardConfigurationError(RuntimeError):
    """Raised when a required runtime configuration value is missing."""


class DriftGuardState(TypedDict, total=False):
    """Mutable state shared by every LangGraph node."""

    # Inputs
    issue_description: str
    aws_event: Dict[str, Any]
    dry_run: bool

    # Triage output
    triage_category: str
    severity: str
    should_remediate: bool
    triage_reason: str

    # Impact analysis output
    impact_summary: str

    # Remediation output
    proposed_hcl: str
    reason_for_fix: str

    # Terraform validation output
    is_valid: bool
    validation_errors: str
    validation_output: str
    validation_terminal_error: bool
    terraform_init_stdout: str
    terraform_init_stderr: str
    terraform_validate_stdout: str
    terraform_validate_stderr: str
    is_policy_compliant: bool
    policy_errors: str
    policy_output: str
    correction_attempts: int
    max_correction_attempts: int

    # GitHub pull request output
    pr_url: str
    pr_branch: str
    pr_error: str
    pr_preview_body: str

    # Operational errors
    llm_error: str
    terminal_error: bool


class TriageDecision(BaseModel):
    """Strict LLM response for drift classification."""

    category: Literal["security", "cost", "compliance", "operational", "unknown"] = Field(
        description="Primary drift category."
    )
    severity: Literal["critical", "high", "medium", "low", "informational"] = Field(
        description="Risk severity if the drift is left unresolved."
    )
    should_remediate: bool = Field(
        description="True when Terraform remediation should be generated."
    )
    reason: str = Field(description="Concise reason for the triage decision.")


class ImpactAnalysis(BaseModel):
    """Strict LLM response for PR-ready cost and security impact analysis."""

    summary_markdown: str = Field(
        description=(
            "Brief Markdown with a security risk summary and an estimated monthly "
            "cost impact. Use clear headings or bullets."
        )
    )


class TerraformRemediation(BaseModel):
    """Strict LLM response for generated remediation code."""

    reason_for_fix: str = Field(
        description="Short explanation of why this Terraform change remediates the drift."
    )
    terraform_hcl: str = Field(
        description="Complete Terraform HCL for main.tf. Do not wrap it in Markdown fences."
    )


class TerraformCommandResult(BaseModel):
    """Normalized subprocess result for Terraform commands."""

    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing_binary: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.missing_binary


def build_llm(provider: Optional[str] = None, model_name: Optional[str] = None) -> Any:
    """
    Build the chat model used by all LLM-backed nodes.

    The provider and model are intentionally environment-driven so production
    deployments can pin approved models without code changes.
    """

    provider = (provider or os.getenv("DRIFTGUARD_LLM_PROVIDER", "openai")).lower()
    model_name = model_name or os.getenv("DRIFTGUARD_LLM_MODEL")
    temperature = float(os.getenv("DRIFTGUARD_LLM_TEMPERATURE", "0"))

    if not model_name:
        raise DriftGuardConfigurationError(
            "Set DRIFTGUARD_LLM_MODEL to the approved OpenAI or Anthropic model name."
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name, temperature=temperature)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, temperature=temperature)

    raise DriftGuardConfigurationError(
        "DRIFTGUARD_LLM_PROVIDER must be either 'openai' or 'anthropic'."
    )


def invoke_structured_llm(schema: Type[BaseModel], messages: list[Any]) -> BaseModel:
    """Invoke the configured LLM and require a Pydantic-shaped response."""

    if as_bool_env("DRIFTGUARD_MOCK_LLM", default=False):
        return mock_structured_response(schema, messages)

    return build_llm().with_structured_output(schema).invoke(messages)


def mock_structured_response(schema: Type[BaseModel], messages: list[Any]) -> BaseModel:
    """
    Deterministic local demo responses.

    This is intentionally opt-in through DRIFTGUARD_MOCK_LLM or --mock-llm so
    production runs always use a real approved model.
    """

    if schema is TriageDecision:
        return TriageDecision(
            category="security",
            severity="high",
            should_remediate=True,
            reason=(
                "The drift appears to expose an AWS resource publicly and should "
                "be remediated through Terraform."
            ),
        )

    if schema is ImpactAnalysis:
        return ImpactAnalysis(
            summary_markdown=(
                "- **Security risk:** Public access drift can expose sensitive data "
                "or create an unintended internet-facing attack surface.\n"
                "- **Estimated monthly cost impact:** Usually low direct cloud spend, "
                "but high incident/compliance exposure if abused or discovered in audit.\n"
                "- **Operational impact:** Creates manual remediation work and weakens "
                "confidence that Terraform reflects production."
            )
        )

    if schema is TerraformRemediation:
        return TerraformRemediation(
            reason_for_fix=(
                "Adds an explicit S3 public access block so Terraform enforces "
                "private bucket posture and reviewers can approve the remediation."
            ),
            terraform_hcl=(
                'terraform {\n'
                '  required_version = ">= 1.5.0"\n\n'
                '  required_providers {\n'
                '    aws = {\n'
                '      source  = "hashicorp/aws"\n'
                '      version = ">= 5.0"\n'
                '    }\n'
                '  }\n'
                '}\n\n'
                'variable "bucket_name" {\n'
                '  description = "Name of the drifted S3 bucket to lock down."\n'
                '  type        = string\n'
                '  default     = "example-public-assets"\n'
                '}\n\n'
                'resource "aws_s3_bucket_public_access_block" "driftguard" {\n'
                '  bucket = var.bucket_name\n\n'
                '  block_public_acls       = true\n'
                '  block_public_policy     = true\n'
                '  ignore_public_acls      = true\n'
                '  restrict_public_buckets = true\n'
                '}\n'
            ),
        )

    raise DriftGuardConfigurationError(f"No mock response is defined for schema {schema}.")


def strip_markdown_code_fence(text: str) -> str:
    """Protect downstream Terraform CLI calls from accidental fenced output."""

    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def as_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


SENSITIVE_KEY_RE = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|access[_-]?key|private[_-]?key|session)",
    re.IGNORECASE,
)
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
AWS_ACCOUNT_ID_RE = re.compile(r"\b\d{12}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(secret|token|password|api[_-]?key|access[_-]?key)\s*[:=]\s*['\"]?[^'\"\s,}]+"
)


def redact_string(value: str) -> str:
    """Remove common credentials and account identifiers before LLM/API logging."""

    redacted = AWS_ACCESS_KEY_RE.sub("[AWS_ACCESS_KEY_ID]", value)
    redacted = AWS_ACCOUNT_ID_RE.sub("[AWS_ACCOUNT_ID]", redacted)
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted


def redact_sensitive_data(value: Any) -> Any:
    """Recursively redact sensitive keys and values from events sent to the LLM."""

    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted

    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]

    if isinstance(value, str):
        return redact_string(value)

    return value


def triage_node(state: DriftGuardState) -> DriftGuardState:
    """Classify the drift event and decide whether autonomous remediation is appropriate."""

    issue_description = state.get("issue_description", "").strip()
    redacted_issue_description = redact_string(issue_description)
    redacted_aws_event = redact_sensitive_data(state.get("aws_event", {}))

    if not issue_description:
        return {
            **state,
            "should_remediate": False,
            "triage_category": "unknown",
            "severity": "informational",
            "triage_reason": "No issue_description was provided.",
        }

    try:
        decision = invoke_structured_llm(
            TriageDecision,
            [
                (
                    "system",
                    (
                        "You are a principal cloud security engineer triaging AWS "
                        "infrastructure drift. Decide whether Terraform remediation "
                        "should be generated. Be conservative for destructive or "
                        "ambiguous changes."
                    ),
                ),
                (
                    "human",
                    (
                        f"Issue description:\n{redacted_issue_description}\n\n"
                        f"Redacted AWS event, if available:\n{redacted_aws_event}"
                    ),
                ),
            ],
        )
    except Exception as exc:
        return {
            **state,
            "should_remediate": False,
            "triage_category": "unknown",
            "severity": "informational",
            "triage_reason": "Triage failed before remediation could be attempted.",
            "llm_error": f"Triage LLM failure: {exc}",
            "terminal_error": True,
        }

    typed_decision = TriageDecision.model_validate(decision)
    return {
        **state,
        "triage_category": typed_decision.category,
        "severity": typed_decision.severity,
        "should_remediate": typed_decision.should_remediate,
        "triage_reason": typed_decision.reason,
        "correction_attempts": state.get("correction_attempts", 0),
        "max_correction_attempts": state.get(
            "max_correction_attempts", DEFAULT_MAX_CORRECTION_ATTEMPTS
        ),
    }


def impact_analyzer_node(state: DriftGuardState) -> DriftGuardState:
    """
    Generate a PR-ready cost and security impact summary before remediation.

    This node is intentionally separate from remediation so the PR explains the
    business impact, not just the implementation details.
    """

    redacted_issue_description = redact_string(state.get("issue_description", ""))

    try:
        impact = invoke_structured_llm(
            ImpactAnalysis,
            [
                (
                    "system",
                    (
                        "You are DriftGuard AI's cost and security impact analyst. "
                        "Produce concise Markdown suitable for a GitHub PR. Include "
                        "security risk and estimated monthly cost impact. If exact "
                        "pricing is unknowable from the event, state a defensible "
                        "range or qualitative estimate."
                    ),
                ),
                (
                    "human",
                    (
                        f"Issue description:\n{redacted_issue_description}\n\n"
                        f"Triage category: {state.get('triage_category', 'unknown')}\n"
                        f"Severity: {state.get('severity', 'unknown')}\n"
                        f"Triage reason: {state.get('triage_reason', '')}"
                    ),
                ),
            ],
        )
    except Exception as exc:
        return {
            **state,
            "impact_summary": (
                "- **Security risk:** Impact analysis failed before a model response was returned.\n"
                "- **Estimated monthly cost impact:** Unknown.\n"
                "- **Operational impact:** Manual review is required before remediation."
            ),
            "llm_error": f"Impact analysis LLM failure: {exc}",
        }

    typed_impact = ImpactAnalysis.model_validate(impact)
    return {**state, "impact_summary": typed_impact.summary_markdown.strip()}


def remediate_node(state: DriftGuardState) -> DriftGuardState:
    """
    Draft or correct Terraform remediation HCL.

    On retry, validation_errors and the previous HCL are sent back to the LLM so
    the correction loop is deterministic and bounded by max_correction_attempts.
    """

    correction_attempts = state.get("correction_attempts", 0)
    validation_errors = state.get("validation_errors", "").strip()
    previous_hcl = state.get("proposed_hcl", "").strip()
    redacted_issue_description = redact_string(state.get("issue_description", ""))

    try:
        remediation = invoke_structured_llm(
            TerraformRemediation,
            [
                (
                    "system",
                    (
                        "You are a Terraform remediation agent for AWS drift. Return "
                        "complete, syntactically valid HCL for a single main.tf file. "
                        "Prefer least-privilege security controls, explicit provider "
                        "requirements, and safe, non-destructive remediation. Do not "
                        "invent account-specific identifiers unless they are present "
                        "in the issue description. If policy feedback is supplied, "
                        "remove the unsafe pattern and keep the remediation reviewable."
                    ),
                ),
                (
                    "human",
                    (
                        f"Issue description:\n{redacted_issue_description}\n\n"
                        f"Impact summary:\n{state.get('impact_summary', '')}\n\n"
                        f"Triage reason:\n{state.get('triage_reason', '')}\n\n"
                        f"Correction attempt: {correction_attempts}\n\n"
                        f"Previous Terraform HCL:\n{previous_hcl or 'None'}\n\n"
                        f"Validation or policy errors to fix:\n{validation_errors or 'None'}"
                    ),
                ),
            ],
        )
    except Exception as exc:
        return {
            **state,
            "is_valid": False,
            "validation_errors": "Remediation generation failed before HCL was produced.",
            "validation_terminal_error": True,
            "llm_error": f"Remediation LLM failure: {exc}",
            "terminal_error": True,
        }

    typed_remediation = TerraformRemediation.model_validate(remediation)
    return {
        **state,
        "proposed_hcl": strip_markdown_code_fence(typed_remediation.terraform_hcl),
        "reason_for_fix": typed_remediation.reason_for_fix.strip(),
        "is_valid": False,
        "validation_errors": "",
        "validation_output": "",
        "validation_terminal_error": False,
        "is_policy_compliant": False,
        "policy_errors": "",
        "policy_output": "",
    }


def run_terraform_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> TerraformCommandResult:
    """Run Terraform with automation-safe flags and normalized error capture."""

    command_text = " ".join(command)
    env = {
        **os.environ,
        "TF_IN_AUTOMATION": "1",
        "TF_INPUT": "0",
    }

    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return TerraformCommandResult(
            command=command_text,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError:
        return TerraformCommandResult(
            command=command_text,
            returncode=127,
            stderr="Terraform CLI was not found on PATH. Install terraform before validation.",
            missing_binary=True,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return TerraformCommandResult(
            command=command_text,
            returncode=124,
            stdout=stdout,
            stderr=(
                f"{stderr}\nCommand timed out after {timeout_seconds} seconds: {command_text}"
            ).strip(),
            timed_out=True,
        )


def write_terraform_sandbox_files(sandbox_dir: Path, proposed_hcl: str) -> None:
    """
    Write generated HCL into an isolated validation sandbox.

    A local backend is added unless the generated HCL already declares a backend.
    This avoids accidentally initializing a remote backend during validation.
    """

    (sandbox_dir / "main.tf").write_text(proposed_hcl, encoding="utf-8")

    if 'backend "' not in proposed_hcl:
        (sandbox_dir / "backend.tf").write_text(
            (
                'terraform {\n'
                '  backend "local" {\n'
                '    path = "terraform.tfstate"\n'
                "  }\n"
                "}\n"
            ),
            encoding="utf-8",
        )


def result_to_log(result: TerraformCommandResult) -> str:
    """Format Terraform command output for state storage and PR rendering."""

    return (
        f"$ {result.command}\n"
        f"exit_code={result.returncode}\n"
        f"stdout:\n{result.stdout.strip() or '<empty>'}\n\n"
        f"stderr:\n{result.stderr.strip() or '<empty>'}"
    )


def validate_node(state: DriftGuardState) -> DriftGuardState:
    """
    Validate proposed_hcl with the real Terraform CLI in a temporary directory.

    Non-zero stderr/stdout is preserved in validation_errors so the remediation
    node can self-correct HCL defects on the next graph cycle.
    """

    proposed_hcl = state.get("proposed_hcl", "").strip()
    correction_attempts = state.get("correction_attempts", 0)

    if not proposed_hcl:
        return {
            **state,
            "is_valid": False,
            "validation_errors": "No proposed_hcl was generated.",
            "validation_output": "",
            "validation_terminal_error": False,
            "correction_attempts": correction_attempts + 1,
        }

    init_timeout = int(
        os.getenv("TERRAFORM_INIT_TIMEOUT_SECONDS", DEFAULT_TERRAFORM_INIT_TIMEOUT_SECONDS)
    )
    validate_timeout = int(
        os.getenv(
            "TERRAFORM_VALIDATE_TIMEOUT_SECONDS",
            DEFAULT_TERRAFORM_VALIDATE_TIMEOUT_SECONDS,
        )
    )

    with tempfile.TemporaryDirectory(prefix="driftguard-terraform-") as temp_dir:
        sandbox_dir = Path(temp_dir)
        write_terraform_sandbox_files(sandbox_dir, proposed_hcl)

        init_result = run_terraform_command(
            ["terraform", "init", "-input=false", "-no-color"],
            cwd=sandbox_dir,
            timeout_seconds=init_timeout,
        )

        if not init_result.ok:
            errors = init_result.stderr.strip() or init_result.stdout.strip()
            return {
                **state,
                "is_valid": False,
                "validation_errors": errors,
                "validation_output": result_to_log(init_result),
                "validation_terminal_error": init_result.missing_binary or init_result.timed_out,
                "terraform_init_stdout": init_result.stdout,
                "terraform_init_stderr": init_result.stderr,
                "correction_attempts": correction_attempts + 1,
            }

        validate_result = run_terraform_command(
            ["terraform", "validate", "-no-color"],
            cwd=sandbox_dir,
            timeout_seconds=validate_timeout,
        )

        combined_output = f"{result_to_log(init_result)}\n\n{result_to_log(validate_result)}"

        if validate_result.ok:
            return {
                **state,
                "is_valid": True,
                "validation_errors": "",
                "validation_output": combined_output,
                "validation_terminal_error": False,
                "terraform_init_stdout": init_result.stdout,
                "terraform_init_stderr": init_result.stderr,
                "terraform_validate_stdout": validate_result.stdout,
                "terraform_validate_stderr": validate_result.stderr,
            }

        errors = validate_result.stderr.strip() or validate_result.stdout.strip()
        return {
            **state,
            "is_valid": False,
            "validation_errors": errors,
            "validation_output": combined_output,
            "validation_terminal_error": validate_result.missing_binary or validate_result.timed_out,
            "terraform_init_stdout": init_result.stdout,
            "terraform_init_stderr": init_result.stderr,
            "terraform_validate_stdout": validate_result.stdout,
            "terraform_validate_stderr": validate_result.stderr,
            "correction_attempts": correction_attempts + 1,
        }


def collect_policy_violations(hcl: str) -> list[str]:
    """
    Lightweight safety checks for generated remediation HCL.

    This is not a replacement for Checkov/tfsec/tflint in paid deployments, but
    it blocks the most obvious unsafe patterns before DriftGuard opens a PR.
    """

    compact = re.sub(r"\s+", " ", hcl.lower())
    violations: list[str] = []

    if "0.0.0.0/0" in compact and re.search(r"from_port\s*=\s*(22|3389)", compact):
        violations.append("Inbound SSH/RDP from 0.0.0.0/0 is not allowed.")

    if re.search(r"\bacl\s*=\s*\"public-read(?:-write)?\"", compact):
        violations.append("Public S3 ACLs are not allowed in remediation code.")

    for public_access_flag in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        if re.search(rf"\b{public_access_flag}\s*=\s*false\b", compact):
            violations.append(f"S3 public access setting {public_access_flag}=false is unsafe.")

    if (
        re.search(r'"effect"\s*:\s*"allow"', compact)
        and re.search(r'"action"\s*:\s*"\*"', compact)
        and re.search(r'"resource"\s*:\s*"\*"', compact)
    ):
        violations.append("IAM policy grants Allow * on Resource *.")

    return violations


def policy_check_node(state: DriftGuardState) -> DriftGuardState:
    """
    Block known-unsafe Terraform patterns after syntax validation.

    Policy errors are passed back through validation_errors so the remediation
    node can self-correct using the same deterministic loop.
    """

    proposed_hcl = state.get("proposed_hcl", "")
    violations = collect_policy_violations(proposed_hcl)

    if not violations:
        return {
            **state,
            "is_policy_compliant": True,
            "policy_errors": "",
            "policy_output": "No built-in DriftGuard policy violations detected.",
        }

    policy_errors = "\n".join(f"- {violation}" for violation in violations)
    return {
        **state,
        "is_valid": False,
        "is_policy_compliant": False,
        "policy_errors": policy_errors,
        "policy_output": policy_errors,
        "validation_errors": f"Policy check failed:\n{policy_errors}",
        "correction_attempts": state.get("correction_attempts", 0) + 1,
    }


def github_config() -> Dict[str, str]:
    """Read and validate GitHub settings used by pull_request_node."""

    required = {
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        "GITHUB_REPOSITORY": os.getenv("GITHUB_REPOSITORY", ""),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise DriftGuardConfigurationError(
            f"Missing required GitHub environment variables: {', '.join(missing)}"
        )

    return {
        **required,
        "GITHUB_BASE_BRANCH": os.getenv("GITHUB_BASE_BRANCH", "main"),
        "GITHUB_TERRAFORM_FILE_PATH": os.getenv("GITHUB_TERRAFORM_FILE_PATH", "main.tf"),
        "GITHUB_BRANCH_PREFIX": os.getenv("GITHUB_BRANCH_PREFIX", "driftguard/remediate"),
    }


def safe_branch_name(prefix: str, issue_description: str) -> str:
    """Build a unique, GitHub-safe branch name from the drift issue."""

    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", issue_description.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:48] or "aws-drift"
    return f"{prefix}/{slug}-{uuid.uuid4().hex[:8]}".replace("//", "/")


def markdown_code_block(text: str, language: str = "text") -> str:
    """Render command output safely inside Markdown."""

    safe_text = text.replace("```", "` ` `").strip() or "<empty>"
    return f"```{language}\n{safe_text}\n```"


def build_pull_request_body(state: DriftGuardState) -> str:
    """Create the monetization-layer PR body with impact, rationale, and validation proof."""

    validate_output = state.get("terraform_validate_stdout") or state.get("validation_output", "")
    return "\n".join(
        [
            "## DriftGuard AI Remediation",
            "",
            "### Impact Summary",
            "",
            state.get("impact_summary", "_No impact summary generated._").strip(),
            "",
            "### Reason For The Fix",
            "",
            state.get("reason_for_fix", "_No remediation rationale generated._").strip(),
            "",
            "### Triage",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Category | {state.get('triage_category', 'unknown')} |",
            f"| Severity | {state.get('severity', 'unknown')} |",
            f"| Decision | {state.get('triage_reason', '')} |",
            "",
            "### Terraform Validate",
            "",
            markdown_code_block(validate_output),
            "",
            "### Built-In Policy Check",
            "",
            markdown_code_block(
                state.get("policy_output", "Policy check did not run before PR creation.")
            ),
            "",
            "### Changed File",
            "",
            f"`{os.getenv('GITHUB_TERRAFORM_FILE_PATH', 'main.tf')}`",
            "",
            "_Generated by DriftGuard AI after successful local Terraform validation._",
            "",
        ]
    )


def pull_request_node(state: DriftGuardState) -> DriftGuardState:
    """
    Create a branch, commit validated Terraform, and open a GitHub pull request.

    All provider/API failures are returned in state.pr_error so graph execution
    remains observable and can be retried by the caller.
    """

    if not state.get("is_valid"):
        return {**state, "pr_error": "pull_request_node skipped because is_valid is False."}

    if not state.get("is_policy_compliant"):
        return {
            **state,
            "pr_error": "pull_request_node skipped because built-in policy checks did not pass.",
        }

    if state.get("llm_error"):
        return {
            **state,
            "pr_error": f"pull_request_node skipped because an upstream LLM step failed: {state['llm_error']}",
        }

    pr_body = build_pull_request_body(state)

    if state.get("dry_run") or as_bool_env("DRIFTGUARD_DISABLE_PR_CREATION", default=False):
        return {
            **state,
            "pr_preview_body": pr_body,
            "pr_error": "",
        }

    try:
        try:
            from github import Github, GithubException
        except ImportError as exc:
            return {
                **state,
                "pr_error": (
                    "PyGithub is not installed. Install dependencies with "
                    "`pip install -r requirements.txt` before creating PRs."
                ),
            }

        config = github_config()
        github_client = Github(config["GITHUB_TOKEN"])
        repo = github_client.get_repo(config["GITHUB_REPOSITORY"])

        base_branch = config["GITHUB_BASE_BRANCH"]
        base_ref = repo.get_git_ref(f"heads/{base_branch}")
        branch_name = safe_branch_name(
            config["GITHUB_BRANCH_PREFIX"],
            state.get("issue_description", "aws-drift"),
        )

        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)

        file_path = config["GITHUB_TERRAFORM_FILE_PATH"]
        commit_message = "DriftGuard AI Terraform remediation"
        proposed_hcl = state.get("proposed_hcl", "")

        try:
            existing_file = repo.get_contents(file_path, ref=branch_name)
            if isinstance(existing_file, list):
                raise DriftGuardConfigurationError(
                    f"Configured file path points to a directory: {file_path}"
                )
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=proposed_hcl,
                sha=existing_file.sha,
                branch=branch_name,
            )
        except GithubException as exc:
            if exc.status != 404:
                raise
            repo.create_file(
                path=file_path,
                message=commit_message,
                content=proposed_hcl,
                branch=branch_name,
            )

        title = f"DriftGuard AI remediation: {state.get('triage_category', 'AWS drift')}"
        pull_request = repo.create_pull(
            title=title,
            body=pr_body,
            head=branch_name,
            base=base_branch,
        )

        return {
            **state,
            "pr_url": pull_request.html_url,
            "pr_branch": branch_name,
            "pr_error": "",
        }
    except (DriftGuardConfigurationError, GithubException) as exc:
        return {**state, "pr_error": str(exc)}
    except Exception as exc:  # Defensive boundary for external API edge cases.
        return {**state, "pr_error": f"Unexpected GitHub PR failure: {exc}"}


def route_after_triage(state: DriftGuardState) -> Literal["impact_analyzer", "end"]:
    """Only continue autonomous remediation when triage approves it."""

    return "impact_analyzer" if state.get("should_remediate") else "end"


def route_after_validation(state: DriftGuardState) -> Literal["policy_check", "remediate", "end"]:
    """Route syntactically valid HCL to policy checks, invalid HCL to correction, or stop."""

    if state.get("is_valid"):
        return "policy_check"

    if state.get("validation_terminal_error"):
        return "end"

    attempts = state.get("correction_attempts", 0)
    max_attempts = state.get("max_correction_attempts", DEFAULT_MAX_CORRECTION_ATTEMPTS)
    return "remediate" if attempts < max_attempts else "end"


def route_after_policy(state: DriftGuardState) -> Literal["pull_request", "remediate", "end"]:
    """Route policy-compliant HCL to PR creation or send unsafe HCL back for correction."""

    if state.get("is_policy_compliant"):
        return "pull_request"

    attempts = state.get("correction_attempts", 0)
    max_attempts = state.get("max_correction_attempts", DEFAULT_MAX_CORRECTION_ATTEMPTS)
    return "remediate" if attempts < max_attempts else "end"


def build_graph() -> Any:
    """Build the production DriftGuard LangGraph state machine."""

    from langgraph.graph import END, StateGraph

    graph = StateGraph(DriftGuardState)

    graph.add_node("triage", triage_node)
    graph.add_node("impact_analyzer", impact_analyzer_node)
    graph.add_node("remediate", remediate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("policy_check", policy_check_node)
    graph.add_node("pull_request", pull_request_node)

    graph.set_entry_point("triage")
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "impact_analyzer": "impact_analyzer",
            "end": END,
        },
    )
    graph.add_edge("impact_analyzer", "remediate")
    graph.add_edge("remediate", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "policy_check": "policy_check",
            "remediate": "remediate",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "policy_check",
        route_after_policy,
        {
            "pull_request": "pull_request",
            "remediate": "remediate",
            "end": END,
        },
    )
    graph.add_edge("pull_request", END)

    return graph.compile()


def run_driftguard(
    issue_description: str,
    aws_event: Optional[Dict[str, Any]] = None,
    max_correction_attempts: int = DEFAULT_MAX_CORRECTION_ATTEMPTS,
    dry_run: bool = False,
) -> DriftGuardState:
    """Convenience entry point for event handlers, CLIs, and tests."""

    app = build_graph()
    return app.invoke(
        {
            "issue_description": issue_description,
            "aws_event": aws_event or {},
            "correction_attempts": 0,
            "max_correction_attempts": max_correction_attempts,
            "dry_run": dry_run,
        }
    )


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE env file without overriding existing variables."""

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def validate_cli_prerequisites(args: argparse.Namespace) -> list[str]:
    """Return actionable setup errors before the agent spends LLM/API calls."""

    errors: list[str] = []

    if shutil.which("terraform") is None:
        errors.append("Terraform CLI was not found on PATH. Install Terraform before running DriftGuard.")

    using_mock_llm = bool(args.mock_llm or as_bool_env("DRIFTGUARD_MOCK_LLM", default=False))
    if not using_mock_llm:
        provider = os.getenv("DRIFTGUARD_LLM_PROVIDER", "openai").lower()
        model_name = os.getenv("DRIFTGUARD_LLM_MODEL", "").strip()

        if not model_name:
            errors.append("DRIFTGUARD_LLM_MODEL is required for non-mock runs.")

        if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
            errors.append("OPENAI_API_KEY is required when DRIFTGUARD_LLM_PROVIDER=openai.")
        elif provider == "anthropic" and not os.getenv("ANTHROPIC_API_KEY"):
            errors.append("ANTHROPIC_API_KEY is required when DRIFTGUARD_LLM_PROVIDER=anthropic.")
        elif provider not in {"openai", "anthropic"}:
            errors.append("DRIFTGUARD_LLM_PROVIDER must be either openai or anthropic.")

    will_create_pr = not args.dry_run and not as_bool_env("DRIFTGUARD_DISABLE_PR_CREATION")
    if will_create_pr:
        missing_github = [
            name
            for name in ("GITHUB_TOKEN", "GITHUB_REPOSITORY")
            if not os.getenv(name, "").strip()
        ]
        if missing_github:
            errors.append(
                "Live PR creation requires: " + ", ".join(missing_github) + ". Use --dry-run for a preview."
            )

        try:
            import github  # noqa: F401
        except ImportError:
            errors.append("PyGithub is not installed. Run `pip install -r requirements.txt`.")

    return errors


def load_event_payload(path: Path) -> tuple[str, Dict[str, Any]]:
    """Load a drift event JSON fixture or production event payload."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Event file must contain a JSON object.")

    issue_description = str(
        payload.get("issue_description")
        or payload.get("detail", {}).get("issue_description")
        or payload.get("description")
        or ""
    ).strip()

    if not issue_description:
        raise ValueError(
            "Event file must include issue_description, detail.issue_description, or description."
        )

    aws_event = payload.get("aws_event", payload)
    if not isinstance(aws_event, dict):
        aws_event = {"raw_event": aws_event}

    return issue_description, aws_event


def format_run_summary(state: DriftGuardState) -> str:
    """Render a readable CLI summary for demos and operator runs."""

    status = "ready for PR" if state.get("is_valid") and state.get("is_policy_compliant") else "blocked"
    if state.get("pr_url"):
        status = "pull request opened"
    elif state.get("pr_error"):
        status = "PR creation blocked"
    elif state.get("pr_preview_body"):
        status = "dry-run PR preview ready"

    sections = [
        "# DriftGuard AI Run Summary",
        "",
        f"Status: {status}",
        f"Triage: {state.get('severity', 'unknown')} {state.get('triage_category', 'unknown')}",
        f"Self-correction attempts: {state.get('correction_attempts', 0)}",
        "",
        "## Impact Summary",
        state.get("impact_summary", "No impact summary generated.").strip(),
        "",
        "## Fix Rationale",
        state.get("reason_for_fix", "No fix rationale generated.").strip(),
        "",
        "## Terraform Validation",
        state.get("validation_errors") or "Terraform validation passed.",
        "",
        "## Policy Check",
        state.get("policy_errors") or state.get("policy_output", "Policy check did not run."),
    ]

    if state.get("pr_url"):
        sections.extend(["", "## Pull Request", state["pr_url"]])
    elif state.get("pr_preview_body"):
        sections.extend(["", "## Pull Request Preview", state["pr_preview_body"]])
    elif state.get("pr_error"):
        sections.extend(["", "## Pull Request Error", state["pr_error"]])

    if state.get("llm_error"):
        sections.extend(["", "## LLM Error", state["llm_error"]])

    return "\n".join(sections).strip() + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the DriftGuard command-line interface."""

    parser = argparse.ArgumentParser(
        description="Generate, validate, policy-check, and PR Terraform remediation for AWS drift."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--event", type=Path, help="Path to a JSON drift event payload.")
    input_group.add_argument("--issue", help="Plain-English drift issue description.")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="Optional env file.")
    parser.add_argument("--dry-run", action="store_true", help="Render a PR preview without GitHub writes.")
    parser.add_argument(
        "--mock-llm",
        action="store_true",
        help="Use deterministic local demo responses instead of a live LLM.",
    )
    parser.add_argument(
        "--max-correction-attempts",
        type=int,
        default=DEFAULT_MAX_CORRECTION_ATTEMPTS,
        help="Maximum validation/policy self-correction attempts.",
    )
    parser.add_argument("--json", action="store_true", help="Print the final state as JSON.")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    """CLI entry point used by `python driftguard.py` and package scripts."""

    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    load_env_file(args.env_file)

    if args.mock_llm:
        os.environ["DRIFTGUARD_MOCK_LLM"] = "true"

    setup_errors = validate_cli_prerequisites(args)
    if setup_errors:
        print("DriftGuard preflight failed:", file=sys.stderr)
        for setup_error in setup_errors:
            print(f"- {setup_error}", file=sys.stderr)
        return 2

    try:
        if args.event:
            issue_description, aws_event = load_event_payload(args.event)
        else:
            issue_description, aws_event = args.issue or "", {}

        final_state = run_driftguard(
            issue_description=issue_description,
            aws_event=aws_event,
            max_correction_attempts=args.max_correction_attempts,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"DriftGuard run failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(final_state, indent=2, sort_keys=True, default=str))
    else:
        print(format_run_summary(final_state))

    has_blocking_error = bool(
        final_state.get("terminal_error")
        or final_state.get("validation_errors")
        or final_state.get("policy_errors")
        or final_state.get("pr_error")
        or final_state.get("llm_error")
    )
    return 1 if has_blocking_error else 0


__all__ = [
    "DriftGuardState",
    "build_graph",
    "collect_policy_violations",
    "format_run_summary",
    "impact_analyzer_node",
    "main",
    "policy_check_node",
    "pull_request_node",
    "redact_sensitive_data",
    "redact_string",
    "remediate_node",
    "run_driftguard",
    "triage_node",
    "validate_cli_prerequisites",
    "validate_node",
]


if __name__ == "__main__":
    raise SystemExit(main())
