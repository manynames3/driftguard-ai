/* Optional browser QA; Playwright is a development tool, not a site dependency. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const { chromium } = await import(process.env.DRIFTGUARD_PLAYWRIGHT_MODULE || "playwright");
const origin = process.env.DRIFTGUARD_PREVIEW_URL || "http://127.0.0.1:4176";
const root = fileURLToPath(new URL("../", import.meta.url));
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const page = await context.newPage();
const errors = [];
const checks = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });

async function layout(label) {
  const result = await page.evaluate(() => {
    const brokenImages = Array.from(document.images).filter((img) => !img.complete || !img.naturalWidth).map((img) => img.src);
    const clippedControls = Array.from(document.querySelectorAll("button, .button, h1, h2, h3")).filter((el) =>
      el.getClientRects().length && el.scrollWidth > el.clientWidth + 2).map((el) => el.textContent.trim());
    return { width: innerWidth, height: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth, brokenImages, clippedControls };
  });
  assert.equal(result.overflow, false, label + ": horizontal overflow");
  assert.deepEqual(result.brokenImages, [], label + ": missing images");
  assert.deepEqual(result.clippedControls, [], label + ": clipped text");
  checks.push({ label, ...result });
}

function payload(key, blocked = false) {
  return {
    mode: "lambda-real-terraform-validate", run_id: "browser-test-only", status: blocked ? "blocked" : "dry_run_ready",
    scenario: { key }, triage: { severity: "high", category: "security", reason: "Synthetic API contract test" },
    impact_summary: "Synthetic test impact", terraform: { hcl: "terraform {}", is_valid: !blocked,
      validation_output: blocked ? "Fixture error output" : "Fixture validation output", validation_errors: blocked ? "Invalid fixture" : "" },
    policy: { is_compliant: !blocked, output: "Fixture policy output" },
    pull_request: { preview_body: "This synthetic preview must be hidden if checks fail", url: "", created: false },
  };
}

try {
  await mkdir(root + "docs/screenshots", { recursive: true });
  for (const key of ["s3", "security-group", "rds"]) {
    await page.goto(origin + "/demo.html?scenario=" + key);
    await page.locator("[data-run-demo]").click();
    await page.locator("[data-result-content]").waitFor({ state: "visible" });
    for (const view of ["impact", "terraform", "validation", "pr"]) {
      await page.locator('[data-view="' + view + '"]').click();
      assert.ok((await page.locator("[data-evidence-body]").innerText()).length > 20);
    }
    assert.match(await page.locator("[data-result-mode]").innerText(), /Simulated/);
    assert.match(await page.locator("[data-evidence-body]").innerText(), /not validated by Terraform/);
    await layout(key + " desktop evidence");
    await page.locator("[data-reset-demo]").click();
    assert.equal(await page.locator("[data-empty]").isVisible(), true);
  }

  await page.goto(origin + "/demo.html?scenario=s3");
  await page.locator("[data-run-demo]").click();
  await page.locator("[data-view=validation]").click();
  await page.evaluate(() => scrollTo(0, document.querySelector(".drift-context").offsetTop - 100));
  await page.screenshot({ path: root + "site/assets/demo-evidence.png" });

  for (const viewport of [{ width: 1440, height: 900 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }, { width: 320, height: 568 }]) {
    await page.setViewportSize(viewport);
    await page.goto(origin + "/index.html");
    await layout("homepage " + viewport.width);
    const localLinks = await page.evaluate(() => Array.from(new Set(Array.from(document.querySelectorAll("a[href]"))
      .map((a) => new URL(a.href)).filter((url) => url.origin === location.origin).map((url) => url.pathname))));
    for (const path of localLinks) assert.equal((await context.request.get(origin + path)).ok(), true);
    const missingAnchors = await page.evaluate(() => Array.from(document.querySelectorAll('a[href^="#"]'))
      .filter((a) => !document.getElementById(a.getAttribute("href").slice(1))).map((a) => a.getAttribute("href")));
    assert.deepEqual(missingAnchors, []);
    const pilot = new URL(await page.locator("[data-pilot-link]").getAttribute("href"));
    assert.equal(pilot.hostname, "github.com");
    assert.match(pilot.searchParams.get("body"), /Do not include credentials/);
    if (viewport.width === 1440) await page.screenshot({ path: root + "docs/screenshots/landing-desktop.png" });
    if (viewport.width === 390) await page.screenshot({ path: root + "docs/screenshots/landing-mobile.png" });
    await page.goto(origin + "/demo.html?scenario=rds");
    await page.locator("[data-run-demo]").click();
    await page.locator("[data-view=terraform]").click();
    await layout("RDS demo " + viewport.width);
    if (viewport.width === 390) {
      await page.locator("[data-results]").scrollIntoViewIfNeeded();
      await page.screenshot({ path: root + "docs/screenshots/demo-mobile.png" });
    }
  }
  assert.deepEqual(errors, [], "Normal flows have console or page errors");
  checks.push({ label: "normal flows", consoleErrors: 0, scenarios: 3, evidenceViewsPerScenario: 4 });

  // Controlled API fixtures test frontend behavior, not a deployed Lambda.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/demo-config.js", (route) => route.fulfill({ contentType: "text/javascript", body: 'window.DRIFTGUARD_DEMO_API_URL="' + origin + '/api/demo/run";' }));
  let apiCase = "success";
  await page.route("**/api/demo/run", async (route) => {
    assert.deepEqual(route.request().postDataJSON(), { scenario: "s3", create_pr: false });
    if (apiCase === "busy") return route.fulfill({ status: 429, contentType: "application/json", body: "{}" });
    if (apiCase === "late") await new Promise((resolve) => setTimeout(resolve, 150));
    try {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(apiCase === "malformed" ? {} : payload("s3", apiCase === "blocked")) });
    } catch (error) {
      if (apiCase !== "late") throw error;
    }
  });
  for (const mode of ["success", "blocked", "malformed", "busy"]) {
    apiCase = mode;
    await page.goto(origin + "/demo.html?scenario=s3");
    await page.locator("[data-run-demo]").click();
    if (mode === "success") {
      await page.locator("[data-result-content]").waitFor({ state: "visible" });
      assert.match(await page.locator("[data-result-summary]").innerText(), /checks passed/);
    } else if (mode === "blocked") {
      await page.locator("[data-result-content]").waitFor({ state: "visible" });
      assert.match(await page.locator("[data-run-status]").innerText(), /blocked/);
      await page.locator("[data-view=pr]").click();
      assert.doesNotMatch(await page.locator("[data-evidence-body]").innerText(), /must be hidden/);
    } else {
      await page.locator("[data-error]").waitFor({ state: "visible" });
      assert.equal(await page.locator("[data-result-content]").isVisible(), false);
      await page.getByRole("button", { name: "View simulated example" }).click();
      assert.match(await page.locator("[data-result-mode]").innerText(), /Simulated/);
    }
    checks.push({ label: "synthetic API behavior", mode, passed: true });
  }
  apiCase = "late";
  await page.goto(origin + "/demo.html?scenario=s3");
  const requested = page.waitForRequest("**/api/demo/run");
  await page.locator("[data-run-demo]").click();
  await requested;
  await page.locator("[data-reset-demo]").click();
  await new Promise((resolve) => setTimeout(resolve, 200));
  assert.equal(await page.locator("[data-empty]").isVisible(), true);
  assert.equal(await page.locator("[data-result-content]").isVisible(), false);
  checks.push({ label: "reset discards late API response", passed: true });
  await writeFile(root + "docs/screenshots/browser-checks.json", JSON.stringify(checks, null, 2) + "\n");
  console.log(JSON.stringify(checks, null, 2));
} finally {
  await browser.close();
}
