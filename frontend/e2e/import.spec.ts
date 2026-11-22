import { test, expect } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
const credentials = process.env.E2E_PASSWORD
  ? {
      username: process.env.E2E_USERNAME || "operator",
      password: process.env.E2E_PASSWORD,
    }
  : JSON.parse(readFileSync("../.local-operator.json", "utf8"));

test.beforeEach(async ({ page }) => {
  const health = await (await page.request.get("/api/health")).json();
  expect(health.mode, "This deterministic suite requires AI_MODE=mock").toBe(
    "mock",
  );
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill(credentials.username);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "A clean start for your data" }),
  ).toBeVisible();
});

for (const legacy of [false, true]) {
  test(`approval displays ${legacy ? "legacy" : "structured"} advisory concerns with their reviewed mapping version`, async ({
    page,
  }) => {
    await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
      name: "advisory-approval.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        `name,email,signup_date,subscription_tier,country_code\nTest Person,advisory-${Date.now()}@example.com,2026-04-03,pro,IN\n`,
      ),
    });
    for (const field of [
      "name",
      "email",
      "signup_date",
      "subscription_tier",
      "country_code",
    ])
      await page
        .getByLabel(`${field} source`, { exact: true })
        .selectOption(field);
    await page
      .getByLabel("Date format", { exact: true })
      .selectOption("%Y-%m-%d");
    await page
      .getByRole("button", { name: "Save mapping", exact: true })
      .click();
    await page.route("**/api/uploads/*/validate", async (route) => {
      const response = await route.fetch();
      const item = await response.json();
      item.agent_run = {
        mode: "mock",
        model: "test-fixture",
        duration_ms: 0,
        usage: null,
        estimated_cost_usd: null,
        pricing_date: null,
        investigator_findings: [],
        checks: [],
        review: null,
        evidence: [],
        disclaimer: "Deterministic UI test fixture",
        status: "ready_for_human",
        mapping_version: 1,
        findings: [
          {
            field: "country_code",
            issue_type: "model_concern",
            severity: "warning",
            explanation: "Confirm the source column represents country codes.",
            scope: "mapping",
            evidence_ids: [],
            validator_ids: [],
            origin: "model_concern",
            verified: false,
            blocking: false,
          },
        ],
      };
      if (legacy) {
        delete item.agent_run.findings;
        item.agent_run.investigator_findings = [
          "Confirm the source column represents country codes.",
        ];
      }
      await route.fulfill({ response, json: item });
    });
    await page
      .getByRole("button", { name: "Validate all rows", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Review import approval", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(
      "Review the advisory concerns before approving.",
    );
    await expect(dialog).toContainText(
      "Confirm the source column represents country codes.",
    );
    await expect(dialog).toContainText("These concerns refer to AI mapping v1");
    await expect(
      dialog.getByRole("button", { name: "Approve & import", exact: true }),
    ).toBeEnabled();
    await dialog
      .getByRole("button", { name: "Back to review", exact: true })
      .click();
  });
}

test("mock upload, mapping, evidence, approval, import and report", async ({
  page,
}) => {
  mkdirSync("../docs/screenshots", { recursive: true });
  await page.screenshot({
    path: "../docs/screenshots/workspace.png",
    fullPage: true,
  });
  const email = `browser-${Date.now()}@example.com`;
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: "browser-demo.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      `full_name,email_address,joined,plan,country\n Alex Example ,${email},2025-03-04,professional,US\nBad Address,invalid,2025-03-04,basic,IN\n`,
    ),
  });
  await expect(
    page.getByRole("heading", { name: "Column mapping", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Suggest mapping", exact: true })
    .click();
  await expect(
    page.getByText("deterministic-fixture-v1", { exact: true }),
  ).toBeVisible();
  const categoryPreview = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Category transformation preview" }),
  });
  await page
    .getByLabel("subscription_tier source", { exact: true })
    .selectOption("plan");
  await expect(categoryPreview).toContainText("professional → pro");
  await expect(categoryPreview).toContainText("1 affected rows");
  await page.getByRole("button", { name: "View source", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("professional");
  await page.getByRole("button", { name: "Close source", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate all rows", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Validation results", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("email: invalid email address", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/review.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Review import approval", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("1 rejected rows");
  await page
    .getByRole("button", { name: "Approve & import", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Import complete", exact: true }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download error report", exact: true })
    .click();
  expect((await download).suggestedFilename()).toBe("rejected-rows.csv");
  await page
    .getByRole("button", { name: "View customer records", exact: true })
    .click();
  await expect(
    page.getByRole("cell", { name: email, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Import history", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "browser-demo.csv", exact: true }).first(),
  ).toBeVisible();
});

test("manual mapping and explicit date choice, cancel and mobile layout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: "manual.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      `name,email,signup_date,subscription_tier,country_code\nManual Person,manual-${Date.now()}@example.com,03/04/2025,pro,US\n`,
    ),
  });
  for (const field of [
    "name",
    "email",
    "signup_date",
    "subscription_tier",
    "country_code",
  ])
    await page
      .getByLabel(`${field} source`, { exact: true })
      .selectOption(field);
  await page
    .getByLabel("Date format", { exact: true })
    .selectOption("%d/%m/%Y");
  await page.getByLabel("Category pairs", { exact: true }).nth(1).fill("{");
  await expect(
    page.getByRole("button", { name: "Save mapping", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("country_code source", { exact: true })
    .selectOption("");
  await expect(
    page.getByRole("button", { name: "Save mapping", exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("country_code source", { exact: true })
    .selectOption("country_code");
  await page.getByRole("button", { name: "Save mapping", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate all rows", exact: true })
    .click();
  await expect(page.getByText("2025-04-03", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Cancel and fix the file", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Original row preview", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/screenshots/mobile.png",
    fullPage: true,
  });
});

test("malformed CSV displays actionable failure", async ({ page }) => {
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: "broken.csv",
    mimeType: "text/csv",
    buffer: Buffer.from('name,email\n"unfinished'),
  });
  await expect(page.getByRole("alert")).toContainText("malformed CSV");
});
