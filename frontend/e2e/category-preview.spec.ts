import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test.use({ actionTimeout: 15000 });

test("real local upfront profiles and deterministic alias preview", async ({
  page,
}) => {
  test.skip(process.env.E2E_CATEGORY !== "1", "Explicit real-model opt-in");
  test.setTimeout(600000);
  const origin = process.env.E2E_BASE_URL || "http://localhost:5173";
  const health = await (await page.request.get("/api/health")).json();
  expect(health.mode).toBe("local");
  await page.goto("/");
  await page
    .getByLabel("Username", { exact: true })
    .fill(process.env.E2E_USERNAME!);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.E2E_PASSWORD!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  const sample = readFileSync(
    "../samples/category-preview.csv",
    "utf8",
  ).replaceAll("@example.com", `+${Date.now()}@example.com`);
  for (const canonical of [false, true]) {
    if (canonical) {
      await page
        .getByRole("button", { name: "New import", exact: true })
        .click();
    }
    await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
      name: canonical ? "canonical-tiers.csv" : "category-preview.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        canonical
          ? sample
              .replaceAll("professional", "pro")
              .replace("gold", "enterprise")
          : sample,
      ),
    });
    const suggestion = page.waitForResponse(
      (response) => response.url().endsWith("/suggest"),
      { timeout: 390000 },
    );
    await page
      .getByRole("button", { name: "Suggest mapping", exact: true })
      .click();
    const response = await suggestion;
    expect(response.ok()).toBe(true);
    const item = await response.json();
    expect(item.agent_run.category.strategy).toBe("profile_lookup");
    expect(item.agent_run.calls.map((c: { agent: string }) => c.agent)).toEqual(
      ["MappingAgent"],
    );
    expect(item.agent_run.category.source_profile.strong_candidate).toBe(
      "membership_band",
    );
    const category = item.mapping.rules.find(
      (r: { destination: string }) => r.destination === "subscription_tier",
    );
    console.log(
      JSON.stringify({
        canonical,
        source: category?.source,
        pairs: category?.categories,
        stage: item.agent_run.category,
        calls: item.agent_run.calls.map(
          (call: { agent: string; duration_ms: number }) => ({
            name: call.agent,
            ms: call.duration_ms,
          }),
        ),
        workflow_ms: item.agent_run.duration_ms,
      }),
    );
    expect(category?.source).toBe("membership_band");
    const panel = page.locator("section").filter({
      has: page.getByRole("heading", {
        name: "Category transformation preview",
      }),
    });
    await expect(
      panel.getByText("Import validation incomplete."),
    ).toBeVisible();
    await panel.getByText("Tier source coverage", { exact: true }).click();
    await expect(panel).toContainText("plan 0/4 supported");
    if (canonical) {
      expect(item.agent_run.category.reason).toBe("no_noncanonical_values");
      await expect(panel).toContainText("0 affected rows");
      await expect(panel).toContainText("4 already canonical");
      continue;
    }
    expect(category.categories).toEqual({ professional: "pro" });
    await expect(panel).toContainText("professional → pro");
    await expect(panel).toContainText("2 affected rows");
    await expect(panel).toContainText("gold (1)");
    await panel.getByRole("button", { name: "View alias policy" }).click();
    await expect(page.getByRole("dialog")).toContainText("professional → pro");
    await page
      .getByRole("button", { name: "Close source", exact: true })
      .click();
    await page.getByLabel("Category pairs", { exact: true }).first().fill("{}");
    await expect(panel).toContainText("0 affected rows");
    await expect(panel).toContainText("professional (2)");
    await page
      .getByLabel("Category pairs", { exact: true })
      .first()
      .fill('{"professional":"pro"}');
    for (const [field, source] of [
      ["name", "full_name"],
      ["email", "email_address"],
      ["signup_date", "joined"],
      ["country_code", ""],
    ]) {
      await page
        .getByLabel(`${field} source`, { exact: true })
        .selectOption(source);
    }
    await page
      .getByLabel("Date format", { exact: true })
      .selectOption("%d/%m/%Y");
    await expect(panel.getByText("Import validation incomplete.")).toHaveCount(
      0,
    );
    await page
      .getByRole("button", { name: "Save mapping", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Validate all rows", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Review import approval", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText(
      "Import 3 valid customer records?",
    );
    await page
      .getByRole("button", { name: "Approve & import", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Import complete" }),
    ).toBeVisible();
    const detail = await (
      await page.request.get(`${origin}/api/uploads/${item.id}`)
    ).json();
    expect(detail.result).toMatchObject({ imported: 3, rejected: 1 });
  }
  await page.getByRole("button", { name: "New import", exact: true }).click();
  await page.getByLabel("Upload CSV", { exact: true }).setInputFiles({
    name: "competing-tiers.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "name,email,joined,service_level,product_band\n" +
        "Ava,ava.tie@example.com,03/04/2026,basic,starter\n" +
        "Kim,kim.tie@example.com,03/04/2026,pro,professional\n" +
        "Lee,lee.tie@example.com,03/04/2026,enterprise,business\n",
    ),
  });
  await page
    .getByRole("button", { name: "Suggest mapping", exact: true })
    .click();
  await expect(
    page.getByText("Tier coverage is tied or too close across columns."),
  ).toBeVisible({ timeout: 180000 });
  await expect(
    page.getByLabel("subscription_tier source", { exact: true }),
  ).toHaveValue("");
  await page
    .getByLabel("subscription_tier source", { exact: true })
    .selectOption("service_level");
  await expect(
    page.getByText("3 already canonical", { exact: false }),
  ).toBeVisible();
});
