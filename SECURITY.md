# Security Boundary

DriftGuard AI is designed to create reviewable Terraform pull requests, not to apply infrastructure changes.

## Current Controls

- No `terraform apply` path exists.
- Drift event text and AWS event payloads are redacted before LLM prompts.
- Terraform validation runs in a temporary local directory.
- Built-in policy checks block obvious unsafe HCL before PR creation.
- PR creation is skipped if validation fails, policy checks fail, or an upstream LLM step fails.
- Dry-run mode renders the PR body without writing to GitHub.

## Known Limitations

- Built-in policy checks are intentionally narrow and should not be treated as complete cloud security coverage.
- Redaction covers common secret and AWS account patterns, but production deployments should add organization-specific data-loss-prevention rules.
- The current GitHub integration supports token-based authentication. Paid deployments should use a least-privilege GitHub App installation token.
- Run history is not persisted yet, so this repo does not currently provide a durable audit trail.

## Production Recommendations

- Add Checkov, tfsec, or OPA policy packs before customer use.
- Use GitHub App auth with repository-scoped permissions.
- Store run history, prompts, redacted inputs, validation results, policy results, and PR URLs.
- Add structured logging and alerting for failed runs.
- Keep `DRIFTGUARD_DISABLE_PR_CREATION=true` in any environment that should never write to GitHub.
