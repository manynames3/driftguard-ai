const sampleEvent = {
  issue_description:
    "S3 bucket example-public-assets drifted from Terraform and now allows public access. Remediate by enforcing S3 public access blocking in Terraform.",
  aws_event: {
    source: "aws.s3",
    "detail-type": "DriftGuard Demo Drift Event",
    account: "123456789012",
    region: "us-east-1",
    resources: ["arn:aws:s3:::example-public-assets"],
    detail: {
      resource_type: "aws_s3_bucket_public_access_block",
      resource_id: "example-public-assets",
      drift_type: "public_access_enabled",
      expected: {
        block_public_acls: true,
        block_public_policy: true,
        ignore_public_acls: true,
        restrict_public_buckets: true,
      },
      actual: {
        block_public_acls: false,
        block_public_policy: false,
        ignore_public_acls: false,
        restrict_public_buckets: false,
      },
    },
  },
};

const terraformHcl = `terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "bucket_name" {
  description = "Name of the drifted S3 bucket to lock down."
  type        = string
  default     = "example-public-assets"
}

resource "aws_s3_bucket_public_access_block" "driftguard" {
  bucket = var.bucket_name

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}`;

const prPreview = `## DriftGuard AI Remediation

### Impact Summary

- **Security risk:** Public access drift can expose sensitive data or create an unintended internet-facing attack surface.
- **Estimated monthly cost impact:** Usually low direct cloud spend, but high incident/compliance exposure if abused or discovered in audit.
- **Operational impact:** Creates manual remediation work and weakens confidence that Terraform reflects production.

### Reason For The Fix

Adds an explicit S3 public access block so Terraform enforces private bucket posture and reviewers can approve the remediation.

### Terraform Validate

\`\`\`text
Success! The configuration is valid.
\`\`\`

### Built-In Policy Check

\`\`\`text
No built-in DriftGuard policy violations detected.
\`\`\``;

const stepOrder = ["triage", "impact", "remediate", "validate", "policy", "pr"];
const outputNode = document.querySelector("[data-demo-output]");
const runButton = document.querySelector("[data-run-demo]");
const resetButton = document.querySelector("[data-reset-demo]");
const eventNode = document.querySelector("[data-event-json]");

eventNode.textContent = JSON.stringify(sampleEvent, null, 2);

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStepState(stepName, state, label) {
  const step = document.querySelector(`[data-step="${stepName}"]`);
  step.dataset.state = state;
  step.querySelector("small").textContent = label;
}

function resetDemo() {
  stepOrder.forEach((stepName) => setStepState(stepName, "idle", "Waiting"));
  outputNode.innerHTML = `
    <div class="empty-output">
      <h3>Ready for a safe dry run</h3>
      <p>The demo will show deterministic output for this sample event. No data leaves this browser session.</p>
    </div>
  `;
  runButton.disabled = false;
}

function appendOutput(title, eyebrow, bodyHtml) {
  outputNode.insertAdjacentHTML(
    "beforeend",
    `<article class="result-card">
      <p class="eyebrow">${eyebrow}</p>
      <h3>${title}</h3>
      ${bodyHtml}
    </article>`,
  );
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function runDemo() {
  resetDemo();
  runButton.disabled = true;
  outputNode.innerHTML = "";

  setStepState("triage", "running", "Running");
  await wait(450);
  appendOutput(
    "Triage: high security",
    "Triage",
    "<p>The drift appears to expose an AWS resource publicly and should be remediated through Terraform.</p>",
  );
  setStepState("triage", "done", "Passed");

  setStepState("impact", "running", "Running");
  await wait(450);
  appendOutput(
    "Impact summary",
    "Risk and cost",
    `<ul>
      <li>Public access drift can expose sensitive data or create an unintended internet-facing attack surface.</li>
      <li>Direct monthly cloud cost is usually low, but incident and compliance exposure can be high.</li>
      <li>The drift weakens confidence that Terraform reflects production.</li>
    </ul>`,
  );
  setStepState("impact", "done", "Ready");

  setStepState("remediate", "running", "Generating");
  await wait(450);
  appendOutput(
    "Generated Terraform",
    "Remediation",
    `<pre><code>${escapeHtml(terraformHcl)}</code></pre>`,
  );
  setStepState("remediate", "done", "Generated");

  setStepState("validate", "running", "Validating");
  await wait(450);
  appendOutput(
    "Terraform validate",
    "Sandbox check",
    `<pre><code>Success! The configuration is valid.</code></pre>`,
  );
  setStepState("validate", "done", "Passed");

  setStepState("policy", "running", "Checking");
  await wait(450);
  appendOutput(
    "Built-in policy check",
    "Safety gate",
    `<pre><code>No built-in DriftGuard policy violations detected.</code></pre>`,
  );
  setStepState("policy", "done", "Passed");

  setStepState("pr", "running", "Preparing");
  await wait(450);
  appendOutput(
    "PR preview",
    "Reviewer package",
    `<pre><code>${escapeHtml(prPreview)}</code></pre>
     <button class="button secondary compact-button" type="button" data-copy-pr>Copy PR preview</button>`,
  );
  setStepState("pr", "done", "Ready");
  runButton.disabled = false;
}

runButton.addEventListener("click", runDemo);
resetButton.addEventListener("click", resetDemo);

document.addEventListener("click", async (event) => {
  if (!event.target.matches("[data-copy-pr]")) {
    return;
  }

  const originalLabel = event.target.textContent;
  try {
    await navigator.clipboard.writeText(prPreview);
    event.target.textContent = "Copied";
  } catch (error) {
    event.target.textContent = "Copy failed";
  }

  window.setTimeout(() => {
    event.target.textContent = originalLabel;
  }, 1800);
});
