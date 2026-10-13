# Verification Record

Recorded on 2026-10-13. These results describe the local implementation, not a new public deployment.

## Automated Checks

| Check | Result |
| --- | --- |
| `python -m pytest` in an isolated environment with project requirements | 18 passed; Terraform installed, no skips |
| `node --test tests/frontend.test.cjs` | 9 passed |
| `python3 scripts/export_demo_scenarios.py --check` | Export matches canonical Python scenarios |
| JavaScript syntax checks | Frontend scripts parse successfully |
| `git diff --check` | No whitespace errors |
| `python scripts/verify_demo_backend.py` | All three scenarios returned real Terraform success, compliant built-in checks, and dry-run PR previews; no PR created |

The backend integration check invokes the Lambda adapter **locally** with mock LLM responses and actual Terraform init/validate. It does not invoke a deployed AWS API, test production credentials, or establish that applying the fixtures is safe.

## Browser Checks

An isolated headless Chrome session exercised:

- S3, security group, and RDS simulations; all four evidence views and reset.
- Homepage and RDS demo at 1440x900, 1920x1080, 390x844, and 320x568.
- No body horizontal overflow, clipped controls/headings, or missing images at those sizes.
- Existing local navigation routes, in-page anchors, and prefilled GitHub inquiry destinations.
- No console/page errors during normal browser flows.
- Controlled API fixtures for successful evidence, failed check gates, malformed responses, HTTP 429, explicit simulated fallback, and late-response cancellation after reset.

The API fixtures exercise frontend behavior; they are **not** actual Lambda execution evidence. Detailed results are in [browser-checks.json](screenshots/browser-checks.json).

## Screenshots

The images are actual browser captures of the revised interface. The demo screenshot is explicitly in browser simulation mode.

![Homepage on desktop](screenshots/landing-desktop.png)

![S3 simulation evidence](../site/assets/demo-evidence.png)

[Mobile homepage](screenshots/landing-mobile.png) and [mobile RDS evidence](screenshots/demo-mobile.png) show the narrow-layout checks.

## Repeat The Checks

Use the README setup and test commands. For the optional local integration check:

```bash
python3 scripts/verify_demo_backend.py
```

This command needs Terraform and network access to install the AWS provider. It forces dry-run/disabled PR creation and disables DynamoDB record writes.

Browser QA uses Playwright as a temporary development tool; it is not a frontend or production dependency:

```bash
npm install --prefix /tmp/driftguard-browser-tools playwright
python3 -m http.server 4176 --bind 127.0.0.1 --directory site
# In another terminal, with Google Chrome installed:
DRIFTGUARD_PLAYWRIGHT_MODULE=/tmp/driftguard-browser-tools/node_modules/playwright/index.mjs \
  node scripts/verify_frontend.mjs
```

The script refreshes the screenshots and browser results. It checks only a local preview by default and never submits a pilot inquiry or creates a PR.

## Unverified Or Unchanged Boundaries

- Publication is separate from this verification record. GitHub commit history and Cloudflare Pages deployment history identify the published revision.
- GitHub About description, homepage, and topics were updated separately through authenticated GitHub CLI access.
- Hosted Lambda health, real model generation quality, private onboarding, billing, and production repository patch safety were not verified by these checks.
- Repowise could not refresh the recovered checkout because it has no local index/sync state. Architecture records were checked against the source. To establish a local wiki, run `repowise init --yes` in the repository root.
