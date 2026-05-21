# DriftGuard AI

DriftGuard AI turns AWS infrastructure drift into reviewable Terraform pull requests.

It triages a drift event, estimates security and cost impact, generates Terraform remediation HCL, validates the HCL with the real Terraform CLI, blocks obvious unsafe patterns, and either opens a GitHub PR or renders a dry-run PR preview.

Live landing page: https://driftguard-ai.pages.dev

Online demo interface with S3, security group, and RDS drift scenarios: https://driftguard-ai.pages.dev/demo

## Who This Is For

- Platform teams using AWS, Terraform, and GitHub.
- Cloud security teams that need faster remediation without skipping review.
- DevOps teams that want drift fixes to land as normal infrastructure pull requests.

## What It Does Today

1. Accepts a plain-English drift description or JSON AWS event.
2. Uses an LLM-backed LangGraph workflow to triage, analyze impact, remediate, validate, and self-correct.
3. Runs `terraform init` and `terraform validate` in a temporary sandbox.
4. Runs built-in policy checks for obvious unsafe Terraform patterns.
5. Opens a GitHub PR, or renders a PR preview in dry-run mode.

## Requirements

- Python 3.10+
- Terraform CLI on `PATH`
- Network access for `terraform init` when generated HCL needs provider plugins
- OpenAI or Anthropic API key for real runs
- GitHub token for live PR creation

## Quickstart Demo

The fastest product demo uses deterministic local LLM responses and does not write to GitHub:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python driftguard.py \
  --event examples/s3_public_access_drift.json \
  --dry-run \
  --mock-llm
```

Expected result: a run summary with impact analysis, Terraform validation output, policy-check output, and a GitHub PR body preview.

The CLI runs preflight checks before invoking the agent. Missing Terraform, LLM keys, model configuration, or GitHub settings are reported before any live API calls are made.

## Real LLM Dry Run

```bash
cp .env.example .env
# Edit .env with your model provider and API key.

python driftguard.py \
  --event examples/s3_public_access_drift.json \
  --dry-run
```

## Live GitHub PR Run

```bash
python driftguard.py \
  --event examples/s3_public_access_drift.json
```

Live PR creation requires:

- `GITHUB_TOKEN`
- `GITHUB_REPOSITORY`
- `GITHUB_BASE_BRANCH`
- `GITHUB_TERRAFORM_FILE_PATH`

For production, use a least-privilege GitHub App installation token instead of a broad personal access token.

## Environment Variables

See [.env.example](.env.example).

Important variables:

- `DRIFTGUARD_LLM_PROVIDER`: `openai` or `anthropic`
- `DRIFTGUARD_LLM_MODEL`: approved model name
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN`: token with branch, contents, and pull request permissions
- `GITHUB_REPOSITORY`: `owner/repo`
- `GITHUB_BASE_BRANCH`: default branch, usually `main`
- `GITHUB_TERRAFORM_FILE_PATH`: file path to create or update in the remediation PR

## Safety Model

DriftGuard does not auto-apply infrastructure changes. It produces reviewable PRs.

Current safety controls:

- Secrets and account IDs are redacted before LLM prompts.
- Terraform is validated in a temporary local sandbox.
- Obvious unsafe Terraform patterns are blocked before PR creation.
- Validation and policy failures are fed back into the remediation loop.
- Dry-run mode renders a PR preview without writing to GitHub.

See [SECURITY.md](SECURITY.md) for security boundaries and production guidance.

Production deployments should add Checkov, tfsec, or OPA policy packs before charging customers. The built-in checks are intentionally small guardrails for the MVP, not a complete cloud security policy engine.

## CLI Usage

```bash
python driftguard.py --help
```

Common options:

- `--event path.json`: load a drift event fixture or production event payload.
- `--issue "description"`: run from a plain-English issue description.
- `--dry-run`: generate a PR preview only.
- `--mock-llm`: use deterministic demo responses.
- `--json`: print final graph state as JSON.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Terraform-dependent tests are skipped automatically when the Terraform CLI is not installed.

## Demo Talk Track

Use this flow when showing DriftGuard to users or hiring managers:

1. "This is not an auto-apply bot. It turns drift into a reviewable Terraform PR."
2. Show the fixture: `cat examples/s3_public_access_drift.json`.
3. Run:

   ```bash
   python driftguard.py \
     --event examples/s3_public_access_drift.json \
     --dry-run \
     --mock-llm
   ```

4. Point out the impact summary, Terraform validation, policy check, and PR preview.
5. Close with the production boundary: real deployments should use GitHub App auth, durable audit logs, and a stronger policy scanner.

## Sales Landing Page

The static landing page lives at [site/index.html](site/index.html). It is aimed at platform and cloud security teams evaluating a focused drift-remediation pilot.

The browser-based demo interface lives at [site/demo.html](site/demo.html). It includes S3 public access, security group exposure, and RDS instance class drift scenarios. By default it uses deterministic browser output. When `window.DRIFTGUARD_DEMO_API_URL` is configured, it calls the AWS Lambda demo backend for real Terraform validation.

The optional AWS demo backend lives in [infra/demo-backend](infra/demo-backend). It keeps idle cost near zero by using API Gateway HTTP API, Lambda, DynamoDB on-demand, short log retention, reserved concurrency, and optional `$5/month` AWS Budget alerts. Public runs stay fixed-scenario and mock-LLM, but Terraform validation is real inside Lambda.

## Frontend Deployment

The Cloudflare Pages frontend serves the static files from `site/`.

```bash
wrangler pages deploy site --project-name driftguard-ai --branch main
```

After deploying the AWS demo backend, set `window.DRIFTGUARD_DEMO_API_URL` in [site/demo-config.js](site/demo-config.js) to the CloudFormation `DemoApiUrl` output and redeploy the frontend. If the API URL is blank or unavailable, the browser demo falls back to the deterministic local simulation.

## Production Boundary

This repo is demo-ready for technical buyers. It is not yet a full SaaS product. Before charging broadly, add a hosted ingestion path, GitHub App auth, durable run history, stronger policy scanning, deployment, and monitoring.
