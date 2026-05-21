# DriftGuard Demo Backend

This backend is designed for a near-zero-idle-cost public demo:

- Cloudflare Pages serves the static frontend.
- API Gateway HTTP API receives `POST /api/demo/run`.
- Lambda runs the fixed demo scenario through the real DriftGuard graph.
- Terraform runs inside the Lambda container image.
- DynamoDB stores compact run history with TTL.
- Reserved concurrency, short timeouts, and an optional AWS Budget alert on spend.

The public API accepts only the three fixed scenarios: `s3`, `security-group`, and `rds`.
It uses deterministic mock LLM output by default, then performs real `terraform init`
and `terraform validate` in Lambda.

## Prerequisites

- AWS CLI authenticated to the account you want to use.
- AWS SAM CLI.
- Docker running locally.
- A budget alert email address if you want the stack to create the `$5` monthly budget.

## Deploy

From the repository root:

```bash
sam build --template-file infra/demo-backend/template.yaml

sam deploy \
  --stack-name driftguard-demo-backend \
  --resolve-image-repos \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    CorsAllowedOrigin=https://driftguard-ai.pages.dev \
    BudgetEmail=you@example.com \
    MonthlyBudgetLimit=5
```

Copy the `DemoApiUrl` output into [site/demo-config.js](../../site/demo-config.js):

```js
window.DRIFTGUARD_DEMO_API_URL = "https://example.execute-api.us-east-1.amazonaws.com/api/demo/run";
```

Then redeploy the frontend:

```bash
wrangler pages deploy site --project-name driftguard-ai --branch main
```

## Test The API

```bash
curl -sS "$DEMO_API_URL" \
  -H "content-type: application/json" \
  -d '{"scenario":"security-group"}' | jq .
```

## Optional Sandbox PR Creation

Public browser runs are dry-run only. To allow admin-only sandbox PR creation:

1. Store an admin key:

   ```bash
   aws ssm put-parameter \
     --name /driftguard/demo/admin-key \
     --type SecureString \
     --value "replace-with-long-random-value" \
     --overwrite
   ```

2. Store a least-privilege GitHub token for a sandbox repo:

   ```bash
   aws ssm put-parameter \
     --name /driftguard/demo/github-token \
     --type SecureString \
     --value "github_pat_or_app_installation_token" \
     --overwrite
   ```

3. Redeploy with sandbox repo parameters:

   ```bash
   sam deploy \
     --stack-name driftguard-demo-backend \
     --resolve-image-repos \
     --capabilities CAPABILITY_IAM \
     --parameter-overrides \
       CorsAllowedOrigin=https://driftguard-ai.pages.dev \
       BudgetEmail=you@example.com \
       MonthlyBudgetLimit=5 \
       GitHubRepository=owner/sandbox-terraform-repo \
       GitHubBaseBranch=main \
       GitHubTerraformFilePath=main.tf
   ```

4. Call the API with the admin key:

   ```bash
   curl -sS "$DEMO_API_URL" \
     -H "content-type: application/json" \
     -H "x-driftguard-demo-key: replace-with-long-random-value" \
     -d '{"scenario":"s3","create_pr":true}' | jq .
   ```

## Cost Controls

- Lambda has no idle compute cost.
- API Gateway HTTP API has no meaningful idle cost.
- DynamoDB is on-demand and stores compact records with TTL.
- CloudWatch log retention is 3 days.
- Lambda reserved concurrency defaults to `2`.
- Lambda timeout defaults to `60` seconds.
- The optional budget sends alerts at 20%, 60%, and 100% of the `$5/month` default.

Avoid adding a VPC, NAT Gateway, RDS database, always-on ECS service, or load balancer to
this demo path. Those are the common ways to break the idle-cost target.
