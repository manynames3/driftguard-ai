# ADR 005: GitHub Issues For Initial Pilot Conversations

**Status:** Accepted; interim access flow.

## Context

There is no signup, email delivery service, billing, or private onboarding backend. Copying a brief leaves interested users without a destination or receipt.

## Decision

Link to the existing repository's GitHub issue composer with a non-sensitive pilot scope. GitHub performs authentication, submission, confirmation, and follow-up. Include a public-data warning and an issue form for future published use. The frontend does not submit on the visitor's behalf.

## Consequences

- A usable inquiry path works with the repository's enabled issues and adds no server cost or credentials.
- It fits technical evaluators but requires a GitHub account.
- No response-time promise, access entitlement, or payment is implied.
- Sensitive infrastructure details require a separately agreed private channel. Replace this with private onboarding before broader paid adoption.
