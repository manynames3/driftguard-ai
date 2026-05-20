const pilotTemplate = `Subject: DriftGuard AI pilot request

Team context:
- AWS account/sandbox:
- Terraform repo:
- GitHub org/repo:

Drift class to pilot:
- Example: S3 public access drift, security group exposure, IAM policy drift

Success criteria:
- Dry-run PR preview produced
- Terraform validate passes
- Policy check passes
- Human reviewer can understand impact and approve or reject the fix`;

async function copyText(text, button, successLabel) {
  const originalLabel = button.textContent;

  try {
    await navigator.clipboard.writeText(text);
    button.textContent = successLabel;
  } catch (error) {
    button.textContent = "Copy failed";
  }

  window.setTimeout(() => {
    button.textContent = originalLabel;
  }, 1800);
}

// This static landing page has no backend request handler yet. The CTA copies a
// pilot brief so the flow is useful without pretending that signup is live.
document.querySelector("[data-copy-template]")?.addEventListener("click", (event) => {
  copyText(pilotTemplate, event.currentTarget, "Pilot brief copied");
});
