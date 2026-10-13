"use strict";

// GitHub owns submission and issue receipts; this page does not pretend signup is live.
document.querySelectorAll("[data-pilot-link]").forEach((link) => {
  link.href = window.DriftGuardDemo.pilotUrl();
});
