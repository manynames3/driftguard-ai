const demoScenarios = {
  s3: {
    label: "S3 drift",
    title: "S3 public access drift",
    description:
      "A bucket's public access controls changed outside Terraform, creating a clear data exposure risk.",
    event: {
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
    },
    triageTitle: "Triage: high security",
    triageBody:
      "The drift appears to expose an AWS storage resource publicly and should be remediated through Terraform.",
    impactBullets: [
      "Public access drift can expose sensitive data or create an unintended internet-facing attack surface.",
      "Direct monthly cloud cost is usually low, but incident and compliance exposure can be high.",
      "The drift weakens confidence that Terraform reflects production.",
    ],
    hcl: `terraform {
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
}`,
    reason:
      "Adds an explicit S3 public access block so Terraform enforces private bucket posture and reviewers can approve the remediation.",
    policyOutput: "No built-in DriftGuard policy violations detected.",
  },
  "security-group": {
    label: "Network drift",
    title: "Security group exposure drift",
    description:
      "An administrative security group was opened to the internet outside the approved Terraform review path.",
    event: {
      issue_description:
        "Security group sg-0baddrift drifted from Terraform and now allows SSH from 0.0.0.0/0. Remediate by restricting SSH to the approved admin CIDR.",
      aws_event: {
        source: "aws.ec2",
        "detail-type": "DriftGuard Demo Drift Event",
        account: "123456789012",
        region: "us-east-1",
        resources: [
          "arn:aws:ec2:us-east-1:123456789012:security-group/sg-0baddrift",
        ],
        detail: {
          resource_type: "aws_security_group",
          resource_id: "sg-0baddrift",
          drift_type: "public_ssh_ingress",
          expected: {
            protocol: "tcp",
            from_port: 22,
            to_port: 22,
            cidr_ipv4: "203.0.113.10/32",
          },
          actual: {
            protocol: "tcp",
            from_port: 22,
            to_port: 22,
            cidr_ipv4: "0.0.0.0/0",
          },
        },
      },
    },
    triageTitle: "Triage: critical security",
    triageBody:
      "The drift opens administrative access to the internet and should be corrected before it becomes a persistent exposure.",
    impactBullets: [
      "Public SSH increases brute-force, credential stuffing, and remote access exposure.",
      "Direct monthly cost is usually low, but incident response and audit exposure can be severe.",
      "The change bypassed Terraform review, so reviewers need clear evidence of the intended network boundary.",
    ],
    hcl: `terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "vpc_id" {
  description = "VPC that owns the drifted administrative security group."
  type        = string
  default     = "vpc-0123456789abcdef0"
}

variable "approved_admin_cidr" {
  description = "Approved administrative access range."
  type        = string
  default     = "203.0.113.10/32"
}

resource "aws_security_group" "app_admin" {
  name        = "app-admin"
  description = "Administrative access restricted by DriftGuard remediation."
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH from approved admin network"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.approved_admin_cidr]
  }

  tags = {
    ManagedBy = "Terraform"
  }
}`,
    reason:
      "Replaces public SSH exposure with an approved administrative CIDR so the intended network boundary is reviewable in Terraform.",
    policyOutput: "No built-in DriftGuard policy violations detected.",
  },
  rds: {
    label: "Cost drift",
    title: "RDS instance class drift",
    description:
      "A database instance was resized outside Terraform, creating cost drift and an unclear rollback path.",
    event: {
      issue_description:
        "RDS instance orders-prod drifted from Terraform. Terraform expects db.t3.medium, but AWS now shows db.r6i.2xlarge. Remediate by restoring the approved instance class in Terraform.",
      aws_event: {
        source: "aws.rds",
        "detail-type": "DriftGuard Demo Drift Event",
        account: "123456789012",
        region: "us-east-1",
        resources: [
          "arn:aws:rds:us-east-1:123456789012:db:orders-prod",
        ],
        detail: {
          resource_type: "aws_db_instance",
          resource_id: "orders-prod",
          drift_type: "instance_class_changed",
          expected: {
            instance_class: "db.t3.medium",
            publicly_accessible: false,
            storage_encrypted: true,
          },
          actual: {
            instance_class: "db.r6i.2xlarge",
            publicly_accessible: false,
            storage_encrypted: true,
          },
        },
      },
    },
    triageTitle: "Triage: medium cost",
    triageBody:
      "The drift changes database capacity outside Terraform and should be reviewed before the larger class becomes the new normal.",
    impactBullets: [
      "A larger RDS class can add hundreds of dollars per month depending on region, storage, and reservation coverage.",
      "Because the change happened outside Terraform, rollback ownership and approval context are unclear.",
      "The generated PR gives reviewers a concrete place to approve the intended database class.",
    ],
    hcl: `terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

variable "db_identifier" {
  description = "Name of the drifted RDS instance."
  type        = string
  default     = "orders-prod"
}

variable "db_password" {
  description = "Existing application database password."
  type        = string
  sensitive   = true
}

resource "aws_db_instance" "orders" {
  identifier          = var.db_identifier
  allocated_storage   = 100
  engine              = "postgres"
  engine_version      = "15.5"
  instance_class      = "db.t3.medium"
  username            = "app_user"
  password            = var.db_password
  skip_final_snapshot = true
  publicly_accessible = false
  storage_encrypted   = true
}`,
    reason:
      "Restores the approved RDS instance class in Terraform so cost drift is visible, reviewable, and reversible through the normal infrastructure workflow.",
    policyOutput:
      "No built-in DriftGuard policy violations detected. Generated RDS posture keeps public access disabled and storage encryption enabled.",
  },
};

const stepOrder = ["triage", "impact", "remediate", "validate", "policy", "pr"];
const outputNode = document.querySelector("[data-demo-output]");
const runButton = document.querySelector("[data-run-demo]");
const resetButton = document.querySelector("[data-reset-demo]");
const eventNode = document.querySelector("[data-event-json]");
const scenarioTitleNode = document.querySelector("[data-scenario-title]");
const scenarioDescriptionNode = document.querySelector("[data-scenario-description]");
const scenarioLabelNode = document.querySelector("[data-scenario-label]");
const scenarioButtons = document.querySelectorAll("[data-scenario-key]");

let selectedScenarioKey = "s3";
let currentPrPreview = "";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function getSelectedScenario() {
  return demoScenarios[selectedScenarioKey];
}

function buildPrPreview(scenario) {
  return `## DriftGuard AI Remediation

### Impact Summary

${scenario.impactBullets.map((bullet) => `- ${bullet}`).join("\n")}

### Reason For The Fix

${scenario.reason}

### Terraform Validate

\`\`\`text
Success! The configuration is valid.
\`\`\`

### Built-In Policy Check

\`\`\`text
${scenario.policyOutput}
\`\`\``;
}

function renderScenario() {
  const scenario = getSelectedScenario();
  eventNode.textContent = JSON.stringify(scenario.event, null, 2);
  scenarioTitleNode.textContent = scenario.title;
  scenarioDescriptionNode.textContent = scenario.description;
  scenarioLabelNode.textContent = scenario.label;
  currentPrPreview = buildPrPreview(scenario);

  scenarioButtons.forEach((button) => {
    const isActive = button.dataset.scenarioKey === selectedScenarioKey;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function setScenarioButtonsDisabled(isDisabled) {
  scenarioButtons.forEach((button) => {
    button.disabled = isDisabled;
  });
}

function setStepState(stepName, state, label) {
  const step = document.querySelector(`[data-step="${stepName}"]`);
  step.dataset.state = state;
  step.querySelector("small").textContent = label;
}

function resetDemo() {
  renderScenario();
  stepOrder.forEach((stepName) => setStepState(stepName, "idle", "Waiting"));
  outputNode.innerHTML = `
    <div class="empty-output">
      <h3>Ready for a safe dry run</h3>
      <p>Pick a scenario and run the deterministic buyer-facing flow. No data leaves this browser session.</p>
    </div>
  `;
  runButton.disabled = false;
  setScenarioButtonsDisabled(false);
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
  const scenario = getSelectedScenario();
  resetDemo();
  runButton.disabled = true;
  setScenarioButtonsDisabled(true);
  outputNode.innerHTML = "";

  setStepState("triage", "running", "Running");
  await wait(450);
  appendOutput(
    scenario.triageTitle,
    "Triage",
    `<p>${escapeHtml(scenario.triageBody)}</p>`,
  );
  setStepState("triage", "done", "Passed");

  setStepState("impact", "running", "Running");
  await wait(450);
  appendOutput(
    "Impact summary",
    "Risk and cost",
    `<ul>
      ${scenario.impactBullets.map((bullet) => `<li>${escapeHtml(bullet)}</li>`).join("")}
    </ul>`,
  );
  setStepState("impact", "done", "Ready");

  setStepState("remediate", "running", "Generating");
  await wait(450);
  appendOutput(
    "Generated Terraform",
    "Remediation",
    `<pre><code>${escapeHtml(scenario.hcl)}</code></pre>`,
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
    `<pre><code>${escapeHtml(scenario.policyOutput)}</code></pre>`,
  );
  setStepState("policy", "done", "Passed");

  setStepState("pr", "running", "Preparing");
  await wait(450);
  currentPrPreview = buildPrPreview(scenario);
  appendOutput(
    "PR preview",
    "Reviewer package",
    `<pre><code>${escapeHtml(currentPrPreview)}</code></pre>
     <button class="button secondary compact-button" type="button" data-copy-pr>Copy PR preview</button>`,
  );
  setStepState("pr", "done", "Ready");
  runButton.disabled = false;
  setScenarioButtonsDisabled(false);
}

scenarioButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (runButton.disabled) {
      return;
    }

    selectedScenarioKey = button.dataset.scenarioKey;
    resetDemo();
  });
});

runButton.addEventListener("click", runDemo);
resetButton.addEventListener("click", resetDemo);

document.addEventListener("click", async (event) => {
  if (!event.target.matches("[data-copy-pr]")) {
    return;
  }

  const originalLabel = event.target.textContent;
  try {
    await navigator.clipboard.writeText(currentPrPreview);
    event.target.textContent = "Copied";
  } catch (error) {
    event.target.textContent = "Copy failed";
  }

  window.setTimeout(() => {
    event.target.textContent = originalLabel;
  }, 1800);
});

resetDemo();
