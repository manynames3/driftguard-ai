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
- The optional Lambda backend persists compact run metadata to DynamoDB with a 30-day TTL by default. This is not a customer audit-history service; the CLI has no durable run store.
- A temporary directory is not hardened isolation for untrusted HCL. Terraform inherits process environment variables, installs providers, and can retain a generated backend declaration. The public API is restricted to fixed fixtures.
- Terraform validate does not prove a deployment is safe. Review a plan, resource/state alignment, and operational impact before applying through your own workflow.
- Browser simulation executes neither Terraform nor the policy scanner. It labels evidence and copied PRs as simulated; failed backend requests require explicit fallback choice.
- The live PR writer creates or replaces the configured Terraform file, rather than calculating a repository-aware patch. Evaluate against a sandbox repository first.
- Pilot inquiries are public GitHub issue drafts. Do not submit credentials, account IDs, private repository URLs, or production data there.

## Production Recommendations

- Add Checkov, tfsec, or OPA policy packs before customer use.
- Use GitHub App auth with repository-scoped permissions.
- Store run history, prompts, redacted inputs, validation results, policy results, and PR URLs.
- Add structured logging and alerting for failed runs.
- Do not store full prompts or infrastructure data without an explicit retention and access policy. Compact demo records and short-lived logs already exist in the optional stack.
- Keep `DRIFTGUARD_DISABLE_PR_CREATION=true` in any environment that should never write to GitHub.
