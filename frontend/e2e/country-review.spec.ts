import { test, expect } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";

test("known country optionality regression with the real local Mapping Agent", async ({
  page,
}) => {
  test.skip(
    process.env.E2E_COUNTRY_REVIEW !== "1",
    "Explicit real-model development reproduction",
  );
  test.setTimeout(600000);
  const credentials = process.env.E2E_PASSWORD
    ? {
        username: process.env.E2E_USERNAME || "operator",
        password: process.env.E2E_PASSWORD,
      }
    : JSON.parse(readFileSync("../.local-operator.json", "utf8"));
  const loadedBefore = await (
    await fetch("http://127.0.0.1:11434/api/ps")
  ).json();
  await page.goto("/");
  await page.getByLabel("Username", { exact: true }).fill(credentials.username);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const stamp = Date.now();
  const filename = `country-review-${stamp}.csv`;
  const countries = ["IN", "IN", "IN", ""];
  const csv =
    "full_name,email_addr,joined_on,plan,country\n" +
    countries
      .map(
        (country, index) =>
          `Development ${index},country-review-${stamp}-${index}@example.com,03/04/2026,${["pro", "basic", "enterprise", "pro"][index]},${country}\n`,
      )
      .join("");
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: filename,
    mimeType: "text/csv",
    buffer: Buffer.from(csv),
  });
  const started = performance.now();
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/suggest") &&
      response.request().method() === "POST",
    { timeout: 590000 },
  );
  await page
    .getByRole("button", { name: "Suggest mapping", exact: true })
    .click();
  const response = await responsePromise;
  const wallMs = Math.round(performance.now() - started);
  expect(response.status(), await response.text()).toBe(200);
  const item = await response.json();
  const report = {
    scenario:
      "Known development regression after the reported 38002ms failure. Three sampled IN values; fourth row blank. Not held-out evidence.",
    wall_ms: wallMs,
    loaded_before: loadedBefore,
    mapping: item.mapping,
    agent_run: item.agent_run,
    loaded_after: await (await fetch("http://127.0.0.1:11434/api/ps")).json(),
  };
  mkdirSync("../.local-evidence", { recursive: true });
  // Save raw observations before assertions so quality failures stay reviewable.
  writeFileSync(
    "../.local-evidence/country-category-regression.json",
    JSON.stringify(report, null, 2),
  );
  expect(item.agent_run.mode).toBe("local");
  expect(item.agent_run.format_version).toBe(3);
  expect(item.agent_run.review).toBeNull();
  expect(item.agent_run.category.reason).toBe("no_noncanonical_values");
  expect(item.agent_run.status).toBe("needs_attention");
  expect(
    item.mapping.rules.find(
      (rule: { destination: string }) => rule.destination === "signup_date",
    ).date_format,
  ).toBeNull();
  expect(
    item.mapping.rules.find(
      (rule: { destination: string }) => rule.destination === "country_code",
    ).source,
  ).toBe("country");
  expect(
    item.agent_run.validator_results.find(
      (result: { id: string }) => result.id === "rows.country_code",
    ),
  ).toMatchObject({ status: "pass", checked_rows: 4, invalid_rows: 0 });
  const countryFindings = item.agent_run.findings.filter(
    (finding: { field: string }) => finding.field === "country_code",
  );
  for (const finding of countryFindings) {
    expect(finding.blocking).toBe(false);
    expect(finding.explanation).not.toMatch(
      /(?:must|required to) be (?:blank|empty)/i,
    );
  }
  expect(
    item.agent_run.findings
      .filter((finding: { blocking: boolean }) => finding.blocking)
      .every((finding: { field: string }) => finding.field === "signup_date"),
  ).toBeTruthy();
  await expect(page.getByLabel("Review findings")).toBeVisible();
  await expect(
    page.getByText("human clarification", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/screenshots/country-review.png",
    fullPage: true,
  });
  const session = await (await page.request.get("/api/session")).json();
  const headers = {
    Origin: process.env.E2E_BASE_URL || "http://localhost:5173",
    "X-CSRF-Token": session.csrf,
  };
  const mapping = structuredClone(item.mapping);
  const date = mapping.rules.find(
    (rule: { destination: string }) => rule.destination === "signup_date",
  );
  date.date_format = "%Y-%m-%d";
  const url = `/api/uploads/${item.id}`;
  expect(
    (
      await page.request.put(url + "/mapping", { headers, data: mapping })
    ).status(),
  ).toBe(200);
  const validation = await (
    await page.request.post(url + "/validate", { headers })
  ).json();
  expect(validation.validation).toMatchObject({ valid: 0, invalid: 4 });
  const rowResponse = await page.request.get(
    url + "/rows?status=invalid&page=1",
  );
  const rows = await rowResponse.json();
  expect(
    rows.rows.every((row: { errors: string[] }) =>
      row.errors.some((error) => error.includes("selected format mismatch")),
    ),
  ).toBeTruthy();
  expect(
    rows.rows.every(
      (row: { errors: string[] }) =>
        !row.errors.some((error) => error.startsWith("country_code:")),
    ),
  ).toBeTruthy();
  writeFileSync(
    "../.local-evidence/country-category-regression.json",
    JSON.stringify(
      {
        ...report,
        explicit_iso_validation: validation.validation,
        row_errors: rows.rows.map(
          (row: { row_number: number; errors: string[] }) => ({
            row_number: row.row_number,
            errors: row.errors,
          }),
        ),
      },
      null,
      2,
    ),
  );
});
