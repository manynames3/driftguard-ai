const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function load(fetch = async () => { throw new Error("Unexpected network request"); }) {
  const context = vm.createContext({ window: { fetch }, URL, AbortController, setTimeout, clearTimeout });
  for (const file of ["scenarios.js", "demo-core.js"]) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../site", file), "utf8"), context);
  }
  return { core: context.window.DriftGuardDemo, window: context.window };
}

function backendPayload(key = "s3") {
  return {
    mode: "lambda-real-terraform-validate", run_id: "test-run", status: "dry_run_ready",
    scenario: { key }, triage: { category: "security", severity: "high", reason: "Fixture" },
    impact_summary: "Fixture", terraform: { is_valid: true, hcl: "terraform {}", validation_output: "Success" },
    policy: { is_compliant: true, output: "Checked" },
    pull_request: { preview_body: "PR", url: "", created: false },
  };
}

test("all three browser fixtures explicitly label checks and copied PRs as simulated", () => {
  const { core } = load();
  for (const key of ["s3", "security-group", "rds"]) {
    const run = core.simulatedRun(key);
    assert.equal(run.terraform.is_valid, null);
    assert.equal(run.policy.is_compliant, null);
    assert.match(run.terraform.validation_output, /Terraform was not executed/);
    assert.match(run.pull_request.preview_body, /simulated PR preview/);
    assert.equal(run.pull_request.created, false);
    assert.ok(run.terraform.hcl.includes("resource"));
  }
});

test("scenario lookup rejects unknown keys and inherited properties", () => {
  const { core } = load();
  assert.throws(() => core.getScenario("toString"), /Unknown/);
  assert.throws(() => core.getScenario("iam"), /Unknown/);
});

test("blocked real checks cannot become a ready PR even with inconsistent backend output", () => {
  const { core } = load();
  for (const field of ["terraform", "policy"]) {
    const payload = backendPayload();
    payload[field][field === "terraform" ? "is_valid" : "is_compliant"] = false;
    const run = core.parseBackendRun(payload, "s3");
    assert.equal(run.status, "blocked");
    assert.equal(run.pull_request.preview_body, "");
    assert.equal(payload.pull_request.preview_body, "PR");
  }
});

test("rejects mismatched, incomplete and unsafe backend results", () => {
  const { core } = load();
  assert.throws(() => core.parseBackendRun({}, "s3"), /incomplete/);
  assert.throws(() => core.parseBackendRun(backendPayload("rds"), "s3"), /incomplete/);
  assert.throws(() => core.parseBackendRun({ ...backendPayload(), triage: {} }, "s3"), /incomplete/);
  const payload = backendPayload();
  payload.pull_request.url = "javascript:alert(1)";
  assert.throws(() => core.parseBackendRun(payload, "s3"), /unexpected PR link/);
});

test("public requests send only a fixed scenario and explicitly disable PR creation", async () => {
  const { core } = load(async (url, options) => {
    assert.equal(url, "https://example.com/api/demo/run");
    assert.deepEqual(JSON.parse(options.body), { scenario: "s3", create_pr: false });
    assert.equal(options.headers["Content-Type"], "application/json");
    return { ok: true, json: async () => backendPayload() };
  });
  const run = await core.requestRun("https://example.com/api/demo/run", "s3");
  assert.equal(run.terraform.is_valid, true);
});

test("busy and network failures stay errors instead of silently switching to simulation", async () => {
  const busy = load(async () => ({ ok: false, status: 429 })).core;
  await assert.rejects(busy.requestRun("https://example.com", "s3"), /busy/);
  const failed = load(async () => { throw new Error("Network failed"); }).core;
  await assert.rejects(failed.requestRun("https://example.com", "s3"), /Network failed/);
});

test("requests abort on timeout and explicit cancellation", async () => {
  const { core } = load((url, { signal }) => new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException("Aborted", "AbortError"));
    if (signal.aborted) return abort();
    signal.addEventListener("abort", abort, { once: true });
  }));
  await assert.rejects(core.requestRun("https://example.com", "s3", undefined, 5), { name: "AbortError" });
  const controller = new AbortController();
  const pending = core.requestRun("https://example.com", "s3", controller.signal);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("API config ignores local storage and permits HTTPS or explicit localhost only", () => {
  const { core, window } = load();
  assert.equal(core.configuredApiUrl(), "");
  window.DRIFTGUARD_DEMO_API_URL = "http://example.com/api";
  assert.throws(() => core.configuredApiUrl(), /HTTPS/);
  window.DRIFTGUARD_DEMO_API_URL = "http://127.0.0.1:4176/api";
  assert.equal(core.configuredApiUrl(), "http://127.0.0.1:4176/api");
});

test("pilot inquiry opens the existing GitHub issue composer with a public-data warning", () => {
  const { core } = load();
  const url = new URL(core.pilotUrl("rds"));
  assert.equal(url.origin, "https://github.com");
  assert.equal(url.pathname, "/manynames3/driftguard-ai/issues/new");
  assert.match(url.searchParams.get("title"), /RDS/);
  assert.match(url.searchParams.get("body"), /Do not include credentials/);
});
