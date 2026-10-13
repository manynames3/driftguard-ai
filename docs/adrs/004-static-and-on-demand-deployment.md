# ADR 004: Static Frontend With An Optional On-Demand Backend

**Status:** Accepted; documents existing deployment shape.

## Context

The demo needs browser access and optional real validation while minimizing idle compute cost. A permanent application server or database is unnecessary for fixed scenarios.

## Decision

Serve plain HTML/CSS/JavaScript from Cloudflare Pages. Use an optional API Gateway HTTP API and Terraform-enabled Lambda container for validation, DynamoDB on-demand for compact TTL records, and SSM for optional admin credentials. Configure concurrency, timeouts, short log retention, and optional budget notifications through SAM.

## Consequences

- Simulation works without AWS deployment or credentials.
- No frontend framework, bundler, always-on server, or VPC/NAT is required.
- Cold starts and provider downloads affect request latency; the frontend times out and supports retry.
- Budget notifications do not enforce a spending ceiling. Abuse protection and traffic controls need further work before broad public usage.
- Persisted metadata is not a customer-accessible history service or tenant audit system.
