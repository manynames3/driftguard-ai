# ADR 002: Fixed Fixtures With Explicit Demo Provenance

**Status:** Accepted.

## Context

A zero-setup demo should show the workflow without accepting arbitrary infrastructure data or charging a model API. A browser cannot honestly claim to have executed Terraform. Separate fixture definitions can silently diverge.

## Decision

Keep three canonical scenarios in `demo_scenarios.py` and generate the browser fixture bundle. Label browser validation, policy evidence, and copied PR output as simulated. The optional backend uses fixed mock LLM responses but executes Terraform. Require an explicit user choice to view simulation after a backend failure.

## Consequences

- Buyers can distinguish product behavior from demonstration scaffolding.
- `--check` detects stale exported fixtures without adding a bundler.
- The frontend validates the API response and blocks misleading PR-ready evidence after failed gates.
- The public demo proves neither live LLM quality nor general AWS drift coverage.
