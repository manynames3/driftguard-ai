"use strict";

const core = window.DriftGuardDemo;
const steps = ["triage", "impact", "remediate", "validate", "policy", "pr"];
const select = (attribute) => document.querySelector("[data-" + attribute + "]");
const scenarioButtons = document.querySelectorAll("[data-scenario-key]");
const viewButtons = document.querySelectorAll("[data-view]");
const runButton = select("run-demo");
const results = select("results");
const requestedKey = new URLSearchParams(window.location.search).get("scenario");
let selectedKey = Object.hasOwn(window.DRIFTGUARD_SCENARIOS, requestedKey) ? requestedKey : "s3";
let activeRun = null;
let sequence = 0;
let runResult = null;
let activeView = "impact";
let copyText = "";
let apiUrl = "";
let configError = "";

try {
  apiUrl = core.configuredApiUrl();
} catch (error) {
  configError = error.message;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function stepState(name, state, label) {
  const step = document.querySelector('[data-step="' + name + '"]');
  step.dataset.state = state;
  step.querySelector("small").textContent = label;
}

function updateMode(simulated = !apiUrl, failed = false) {
  select("mode-banner").dataset.state = simulated ? "simulation" : "backend";
  select("mode-label").textContent = simulated ? "Browser simulation" : "Real validation endpoint configured";
  select("backend-status").textContent = failed
    ? "The validation service did not return usable evidence. You can retry or explicitly view a simulated example."
    : simulated
      ? "Terraform and policy checks are simulated. No scenario data is submitted to a backend."
      : "Submits only a fixed scenario. Mock LLM responses; real Terraform init and validate. No PR is created.";
  if (configError) select("backend-status").textContent = "API configuration error. Showing browser simulation: " + configError;
}

function renderScenario() {
  const scenario = core.getScenario(selectedKey);
  const detail = scenario.aws_event.detail;
  select("scenario-title").textContent = scenario.title;
  select("scenario-description").textContent = scenario.description;
  select("resource").textContent = detail.resource_type + " / " + detail.resource_id;
  select("severity").textContent = scenario.severity + " / " + scenario.triage_category;
  select("severity").dataset.severity = scenario.severity;
  select("expected").textContent = Object.entries(detail.expected).map(([key, value]) => key + " = " + String(value)).join("\n");
  select("actual").textContent = Object.entries(detail.actual).map(([key, value]) => key + " = " + String(value)).join("\n");
  select("event-json").textContent = JSON.stringify({ issue_description: scenario.issue_description, aws_event: scenario.aws_event }, null, 2);
  scenarioButtons.forEach((button) => {
    const selected = button.dataset.scenarioKey === selectedKey;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  select("pilot-link").href = core.pilotUrl(selectedKey);
}

function resetDemo() {
  sequence += 1;
  activeRun?.abort();
  activeRun = null;
  runResult = null;
  activeView = "impact";
  results.setAttribute("aria-busy", "false");
  runButton.disabled = false;
  runButton.textContent = apiUrl ? "Run real validation" : "Run simulated scenario";
  select("empty").hidden = false;
  select("error").hidden = true;
  select("error").replaceChildren();
  select("result-content").hidden = true;
  select("result-mode").textContent = "Not run yet";
  select("run-status").textContent = "Choose a scenario, then inspect its reviewer package.";
  select("copy-evidence").disabled = false;
  scenarioButtons.forEach((button) => { button.disabled = false; });
  steps.forEach((name) => stepState(name, "idle", "Waiting"));
  updateMode();
  renderScenario();
}

function showCode(text) {
  const pre = element("pre");
  pre.append(element("code", text));
  return pre;
}

function renderView() {
  if (!runResult) return;
  const body = select("evidence-body");
  const simulated = runResult.mode === core.previewMode;
  const nodes = [];
  viewButtons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === activeView)));
  if (activeView === "impact") {
    nodes.push(element("h3", runResult.triage?.severity + " " + runResult.triage?.category + " drift"));
    nodes.push(element("p", runResult.triage?.reason || "No triage explanation returned."));
    const list = element("ul", undefined, "impact-list");
    String(runResult.impact_summary || "").split("\n").filter(Boolean).forEach((line) => {
      list.append(element("li", line.replace(/^- /, "").replaceAll("**", "")));
    });
    nodes.push(list, element("p", core.getScenario(selectedKey).reason_for_fix));
    nodes.push(element("p", "Cost context is an estimate. RDS changes also require capacity and downtime review.", "evidence-note"));
    copyText = String(runResult.impact_summary || "");
  } else if (activeView === "terraform") {
    nodes.push(element("h3", "Proposed Terraform / standalone fixture"));
    nodes.push(element("p", "This is proposed HCL, not a repository-aware patch. Match existing resource addresses and state before using it.", "evidence-note"));
    copyText = runResult.terraform.hcl;
    nodes.push(showCode(copyText));
  } else if (activeView === "validation") {
    nodes.push(element("h3", simulated ? "Simulated validation evidence" : "Terraform command evidence"));
    const terraform = runResult.terraform;
    copyText = [terraform.validation_output, terraform.validation_errors, terraform.init_stderr, terraform.validate_stderr].filter(Boolean).join("\n\n");
    if (!copyText) copyText = "No Terraform output was returned. Treat this as missing evidence.";
    nodes.push(showCode(copyText));
    nodes.push(element("h3", simulated ? "Simulated policy result" : "Built-in policy result"));
    const policy = [runResult.policy.output, runResult.policy.errors].filter(Boolean).join("\n\n") || "No policy output returned.";
    nodes.push(showCode(policy), element("p", "Configuration validity does not establish deployment safety. A plan and your policy review are still required.", "evidence-note"));
    copyText += "\n\n" + policy;
  } else {
    nodes.push(element("h3", simulated ? "Simulated PR body / not submitted" : "PR body / dry run"));
    copyText = runResult.pull_request.preview_body || "";
    if (copyText) nodes.push(showCode(copyText));
    else nodes.push(element("p", runResult.pull_request.error || "PR preparation is blocked or no preview was returned."));
    if (runResult.pull_request.url) {
      const link = element("a", "Open the returned sandbox PR", "text-link");
      link.href = runResult.pull_request.url;
      link.rel = "noopener noreferrer";
      nodes.push(link);
    }
  }
  body.replaceChildren(...nodes);
  select("copy-evidence").disabled = !copyText;
  select("copy-evidence").textContent = activeView === "terraform" ? "Copy HCL" : "Copy evidence";
}

function finishRun(payload) {
  runResult = payload;
  const simulated = payload.mode === core.previewMode;
  const checksPassed = !simulated && payload.terraform.is_valid && payload.policy.is_compliant;
  const previewReady = Boolean(payload.pull_request.preview_body || payload.pull_request.url);
  ["triage", "impact", "remediate"].forEach((step) => stepState(step, "done", simulated ? "Example" : "Returned"));
  stepState("validate", simulated ? "simulated" : payload.terraform.is_valid ? "done" : "blocked", simulated ? "Simulated" : payload.terraform.is_valid ? "Passed" : "Blocked");
  stepState("policy", simulated ? "simulated" : payload.policy.is_compliant ? "done" : "blocked", simulated ? "Simulated" : payload.policy.is_compliant ? "Passed" : "Blocked");
  stepState("pr", simulated ? "simulated" : checksPassed && previewReady ? "done" : "blocked", simulated ? "Example" : checksPassed && previewReady ? "Preview ready" : "Blocked");
  select("result-mode").textContent = simulated ? "Simulated example" : "Backend result / " + payload.run_id;
  select("result-mode").dataset.state = simulated ? "simulation" : checksPassed ? "success" : "blocked";
  select("result-summary").textContent = simulated
    ? "Fixed scenario output. Terraform and policy checks were not executed. No GitHub PR was created."
    : checksPassed && previewReady
      ? "Terraform and built-in policy checks passed. A dry-run PR preview was prepared; deployment safety still needs review."
      : "The backend did not produce a review-ready PR. Inspect check errors and missing evidence below.";
  if (!simulated && !checksPassed) activeView = "validation";
  select("run-status").textContent = simulated ? "Simulated reviewer package ready." : checksPassed && previewReady ? "Validation evidence and PR preview ready." : "PR preparation blocked.";
  select("result-content").hidden = false;
  select("empty").hidden = true;
  renderView();
}

async function runDemo(forceSimulation = false) {
  resetDemo();
  const thisSequence = sequence;
  const controller = new AbortController();
  activeRun = controller;
  runButton.disabled = true;
  scenarioButtons.forEach((button) => { button.disabled = true; });
  results.setAttribute("aria-busy", "true");
  select("empty").hidden = true;
  steps.forEach((step) => stepState(step, "running", "Pending"));
  const simulated = forceSimulation || !apiUrl;
  updateMode(simulated);
  select("run-status").textContent = simulated ? "Preparing the fixed scenario example..." : "Requesting real Terraform validation. Cold starts can take up to 35 seconds.";
  try {
    const payload = simulated ? core.simulatedRun(selectedKey) : await core.requestRun(apiUrl, selectedKey, controller.signal);
    if (thisSequence !== sequence) return;
    finishRun(payload);
  } catch (error) {
    if (thisSequence !== sequence) return;
    steps.forEach((step) => stepState(step, "blocked", "No evidence"));
    updateMode(false, true);
    const errorBox = select("error");
    errorBox.hidden = false;
    errorBox.append(element("h3", "Real validation unavailable"));
    errorBox.append(element("p", error.name === "AbortError" ? "The request exceeded 35 seconds. No validated result was received." : error.message));
    errorBox.append(element("p", "Retry real validation, or view the explicitly simulated example."));
    const simulationButton = element("button", "View simulated example", "button secondary");
    simulationButton.type = "button";
    simulationButton.addEventListener("click", () => runDemo(true));
    errorBox.append(simulationButton);
    select("result-mode").textContent = "No validation evidence";
    select("run-status").textContent = "Validation request failed. Retry or choose a simulated example.";
  } finally {
    if (thisSequence === sequence) {
      activeRun = null;
      runButton.disabled = false;
      scenarioButtons.forEach((button) => { button.disabled = false; });
      results.setAttribute("aria-busy", "false");
    }
  }
}

scenarioButtons.forEach((button) => button.addEventListener("click", () => {
  selectedKey = button.dataset.scenarioKey;
  const url = new URL(window.location.href);
  url.searchParams.set("scenario", selectedKey);
  window.history.replaceState(null, "", url);
  resetDemo();
}));
viewButtons.forEach((button) => button.addEventListener("click", () => {
  activeView = button.dataset.view;
  renderView();
}));
runButton.addEventListener("click", () => runDemo());
select("reset-demo").addEventListener("click", resetDemo);
select("copy-evidence").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(copyText);
    select("run-status").textContent = "Evidence copied.";
  } catch {
    select("run-status").textContent = "Clipboard unavailable. The evidence remains visible for selection.";
  }
});
resetDemo();
