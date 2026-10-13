# ADR 001: Bounded, Review-First Remediation

**Status:** Accepted; documents existing implementation.

## Context

An LLM can produce plausible but invalid or unsafe HCL. Infrastructure changes also need a reviewer who understands the current resources and operational constraints.

## Decision

Use a LangGraph state machine with Pydantic outputs, bounded remediation retries, Terraform validation, and built-in policy gates. End with a dry-run PR body or a GitHub PR. Do not include an apply path.

## Consequences

- Failure and correction paths are inspectable and testable.
- Persistent validation/policy failures and upstream errors prevent PR creation.
- Syntax validation and selected policy checks do not establish deployment safety.
- Reviewers still reconcile resource addresses/state and review a plan through their own CI.
