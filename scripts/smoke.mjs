// Real HTTP smoke test for the isolated Compose stack; credentials are supplied via env.
import assert from "node:assert/strict";
const base = process.env.SMOKE_URL || "http://localhost:5273";
let cookie = "",
  csrf = "";
async function request(path, method = "GET", body) {
  const response = await fetch(base + "/api" + path, {
    method,
    headers: {
      Origin: base,
      Cookie: cookie,
      "X-CSRF-Token": csrf,
      ...(body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
    },
    body:
      body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  if (response.headers.get("set-cookie"))
    cookie = response.headers.get("set-cookie").split(";")[0];
  const result = await response.json();
  assert.equal(response.status, 200, JSON.stringify(result));
  return result;
}
const login = await request("/login", "POST", {
  username: process.env.SMOKE_USERNAME || "smoke",
  password: process.env.SETUP_PASSWORD,
});
csrf = login.csrf;
assert.equal(login.mode, "mock");
for (const mode of ["manual", "mock"]) {
  const file = new FormData();
  file.append(
    "file",
    new Blob(
      [
        `name,email,signup_date,subscription_tier,country_code\nSmoke Person,${mode}@example.com,2025-01-01,pro,US\nBad,bad-address,2025-01-01,pro,US\n`,
      ],
      { type: "text/csv" },
    ),
    `${mode}.csv`,
  );
  let upload = await request("/uploads", "POST", file);
  const url = "/uploads/" + upload.id;
  if (mode === "mock") upload = await request(url + "/suggest", "POST");
  else
    upload = await request(url + "/mapping", "PUT", {
      rules: [
        "name",
        "email",
        "signup_date",
        "subscription_tier",
        "country_code",
      ].map((field) => ({
        destination: field,
        source: field,
        trim: true,
        date_format: field === "signup_date" ? "%Y-%m-%d" : null,
        categories: {},
        citations: [],
      })),
    });
  upload = await request(url + "/validate", "POST");
  assert.equal(upload.validation.valid, 1);
  assert.equal(upload.validation.invalid, 1);
  upload = await request(url + "/approve", "POST", {
    version: upload.version,
    validation_hash: upload.validation.hash,
    policy: "valid_only",
  });
  const body = {
    approval_id: upload.approval.id,
    idempotency_key: "clean-" + mode,
  };
  const result = await request(url + "/import", "POST", body);
  assert.equal(result.imported, 1);
  assert.deepEqual(await request(url + "/import", "POST", body), result);
}
assert.equal((await request("/customers")).total, 2);
assert.equal((await fetch(base)).status, 200);
console.log(
  "Clean stack: manual and mock flows, rejected rows, approval, retry and two persisted customers verified.",
);
