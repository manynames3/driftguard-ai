# ADR 003: Terraform Subprocess Validation In Temporary Directories

**Status:** Accepted; documents existing implementation.

## Context

Generated HCL needs actual provider/schema validation, command output, and failure feedback. Running it against the user's deployment state would add unnecessary risk.

## Decision

Write HCL to a temporary directory, add a local backend when none is present, run `terraform init` and `terraform validate` with automation flags and per-command timeouts, and capture return codes/stdout/stderr for the agent and reviewer.

## Consequences

- Genuine Terraform errors can drive bounded self-correction.
- Temporary files are removed after execution; Terraform CLI must be installed or bundled.
- Provider initialization may need network access and dominate latency.
- This is not a hardened isolation boundary: environment variables are inherited and generated backend declarations can remain. Public Lambda input is therefore restricted to known fixtures.
- Terraform validation does not substitute for a plan, state alignment, policy scanning, or operational review.
