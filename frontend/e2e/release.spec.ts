import { test, expect } from "@playwright/test";
import { mkdirSync } from "node:fs";

test("capture public screenshots with synthetic data in an isolated local stack", async ({
  page,
}) => {
  test.skip(
    process.env.E2E_RELEASE !== "1",
    "Explicit public-image capture, excluded from normal CI",
  );
  test.setTimeout(300000);
  expect(process.env.E2E_USERNAME).toBe("demo-operator");
  expect(process.env.E2E_PASSWORD).toBeTruthy();
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await (await page.request.get("/api/health")).json()).mode).toBe(
    "local",
  );
  await page.goto("/");
  await page
    .getByLabel("Username", { exact: true })
    .fill(process.env.E2E_USERNAME!);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const stamp = Date.now();
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: "northstar-demo.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      `full_name,email_address,joined,plan,country\n Maya Chen ,maya-${stamp}@example.com,2025-01-14,professional,US\nArjun Rao,arjun-${stamp}@example.com,2025-02-03,starter,IN\nSofia Weber,sofia-${stamp}@example.com,2025-03-19,business,DE\nOliver Reed,not-an-email,2025-01-23,pro,GB\nAmelia Brooks,amelia-${stamp}@example.com,2025-02-30,basic,CA\nMaya Duplicate,MAYA-${stamp}@EXAMPLE.COM,2025-04-01,basic,US\n`,
    ),
  });
  await page
    .getByRole("button", { name: "Suggest mapping", exact: true })
    .click();
  await expect(page.getByText("qwen3:4b", { exact: true })).toBeVisible({
    timeout: 180000,
  });
  mkdirSync("../docs/images", { recursive: true });
  await page
    .locator("section.card")
    .first()
    .screenshot({ path: "../docs/images/mapping-proposal.png" });
  await page
    .getByRole("row")
    .filter({ hasText: "subscription_tier" })
    .getByRole("button", { name: "View source", exact: true })
    .first()
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  mkdirSync("../docs/images", { recursive: true });
  await page
    .getByRole("dialog")
    .screenshot({ path: "../docs/images/mapping-evidence.png" });
  await page.getByRole("button", { name: "Close source", exact: true }).click();
  for (const [destination, source] of Object.entries({
    name: "full_name",
    email: "email_address",
    signup_date: "joined",
    subscription_tier: "plan",
    country_code: "country",
  })) {
    await page
      .getByLabel(`${destination} source`, { exact: true })
      .selectOption(source);
  }
  await page
    .getByLabel("Date format", { exact: true })
    .selectOption("%Y-%m-%d");
  await page
    .getByLabel("Category pairs", { exact: true })
    .first()
    .fill('{"starter":"basic","professional":"pro","business":"enterprise"}');
  await page.getByLabel("Category pairs", { exact: true }).nth(1).fill("{}");
  await page.getByRole("button", { name: "Save mapping", exact: true }).click();
  await page
    .getByRole("button", { name: "Validate all rows", exact: true })
    .click();
  const validation = page.getByRole("heading", {
    name: "Validation results",
    exact: true,
  });
  await expect(validation).toBeVisible();
  await validation.scrollIntoViewIfNeeded();
  await validation
    .locator("xpath=ancestor::section")
    .screenshot({ path: "../docs/images/validation-preview.png" });
  await page
    .getByRole("button", { name: "Review import approval", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Import 3 valid customer records?",
  );
  await expect(page.getByRole("dialog")).toContainText("3 rejected rows");
  await page
    .getByRole("button", { name: "Approve & import", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Import complete", exact: true }),
  ).toBeVisible();
  await page.locator(".import-success").scrollIntoViewIfNeeded();
  await page
    .locator(".import-success")
    .screenshot({ path: "../docs/images/import-result.png" });
});
