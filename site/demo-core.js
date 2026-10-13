/* Shared evidence and API contract for the homepage and scenario runner. */
(function () {
  "use strict";
  const scenarios = window.DRIFTGUARD_SCENARIOS;
  const previewMode = "browser-simulation";

  function getScenario(key) {
    if (!Object.hasOwn(scenarios, key)) throw new Error("Unknown drift scenario.");
    return scenarios[key];
  }

  function pilotUrl(key) {
    const title = key ? `Pilot inquiry: ${getScenario(key).title}` : "Pilot inquiry: AWS drift remediation";
    const url = new URL("https://github.com/manynames3/driftguard-ai/issues/new");
    url.searchParams.set("title", title);
    url.searchParams.set("body", "## Pilot scope\n\nFirst drift scenario: " +
      (key ? getScenario(key).title : "S3, security group, or RDS") +
      "\n\n## Evaluation outcome\n\nA reviewer can inspect the proposed HCL, understand the impact, and see validation evidence.\n\n## Non-sensitive team context\n\n<!-- This issue is public. Do not include credentials, account IDs, private repository URLs, or production data. -->\n");
    return url.href;
  }

  function simulatedRun(key) {
    const scenario = getScenario(key);
    const validation = "SIMULATED EXAMPLE - Terraform was not executed in this browser.\n\nExpected output from a successful validate run:\nSuccess! The configuration is valid.";
    const policy = "SIMULATED EXAMPLE - policy checks were not executed.\nThe fixed fixture illustrates a passing built-in policy result.";
    return {
      mode: previewMode, status: "simulated_preview",
      scenario: { key, title: scenario.title },
      triage: { category: scenario.triage_category, severity: scenario.severity, reason: scenario.triage_reason },
      impact_summary: scenario.impact_summary,
      terraform: { hcl: scenario.terraform_hcl, is_valid: null, validation_output: validation, validation_errors: "" },
      policy: { is_compliant: null, output: policy, errors: "" },
      pull_request: {
        preview_body: `## DriftGuard AI - simulated PR preview\n\nThis example was not validated by Terraform. No PR was created.\n\n### Impact summary\n\n${scenario.impact_summary}\n\n### Reason for the fix\n\n${scenario.reason_for_fix}\n\n### Terraform validate (simulated)\n\n\`\`\`text\n${validation}\n\`\`\`\n\n### Policy checks (simulated)\n\n${policy}\n\n### Review required\n\nReconcile with existing resources and state, run a plan in your own CI, and review operational impact before applying.`,
        url: "", created: false,
      },
    };
  }

  function parseBackendRun(payload, key) {
    // HTTP 200 alone is not evidence that validation or PR preparation succeeded.
    const valid = payload && payload.mode === "lambda-real-terraform-validate" &&
      payload.scenario?.key === key && typeof payload.run_id === "string" && payload.run_id.trim() !== "" &&
      typeof payload.triage?.severity === "string" && typeof payload.triage?.category === "string" &&
      typeof payload.triage?.reason === "string" && typeof payload.impact_summary === "string" &&
      typeof payload.terraform?.is_valid === "boolean" &&
      typeof payload.terraform?.hcl === "string" &&
      typeof payload.terraform?.validation_output === "string" &&
      typeof payload.policy?.is_compliant === "boolean" &&
      typeof payload.pull_request?.preview_body === "string";
    if (!valid) throw new Error("The validation service returned an incomplete result.");
    const result = { ...payload, pull_request: { ...payload.pull_request } };
    if (!payload.terraform.is_valid || !payload.policy.is_compliant) {
      result.status = "blocked";
      result.pull_request = { ...result.pull_request, preview_body: "", url: "", created: false };
    }
    if (result.pull_request.url) {
      const url = new URL(result.pull_request.url);
      if (url.protocol !== "https:" || url.hostname !== "github.com") {
        throw new Error("The validation service returned an unexpected PR link.");
      }
    }
    return result;
  }

  function configuredApiUrl() {
    const value = String(window.DRIFTGUARD_DEMO_API_URL || "").trim();
    if (!value) return "";
    const url = new URL(value);
    const local = ["127.0.0.1", "localhost"].includes(url.hostname);
    if (url.protocol !== "https:" && !(local && url.protocol === "http:")) {
      throw new Error("The validation API must use HTTPS, or HTTP on localhost.");
    }
    return url.href;
  }

  async function requestRun(apiUrl, key, signal, timeoutMs = 35000) {
    getScenario(key);
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setTimeout(cancel, timeoutMs);
    try {
      if (signal?.aborted) controller.abort();
      const response = await window.fetch(apiUrl, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: key, create_pr: false }), signal: controller.signal,
      });
      if (!response.ok) {
        if (response.status === 429) throw new Error("The validation service is busy. Try again shortly.");
        throw new Error(`The validation service returned HTTP ${response.status}.`);
      }
      return parseBackendRun(await response.json(), key);
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
  }

  window.DriftGuardDemo = { getScenario, pilotUrl, simulatedRun, parseBackendRun, configuredApiUrl, requestRun, previewMode };
})();
