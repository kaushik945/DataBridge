import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { createHash } from "node:crypto";

const output = process.argv[2];
if (!output) throw new Error("Supply a fresh output filename");
mkdirSync(dirname(output), { recursive: true });
const credentials = process.env.E2E_PASSWORD
  ? {
      username: process.env.E2E_USERNAME || "operator",
      password: process.env.E2E_PASSWORD,
    }
  : JSON.parse(readFileSync(".local-operator.json", "utf8"));
const login = await fetch("http://localhost:5173/api/login", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Origin: "http://localhost:5173",
  },
  body: JSON.stringify(credentials),
});
if (!login.ok) throw new Error(`Login failed ${login.status}`);
const session = await login.json();
const cookie = login.headers.get("set-cookie").split(";")[0];
const headers = {
  Cookie: cookie,
  Origin: "http://localhost:5173",
  "X-CSRF-Token": session.csrf,
};
const fixedCsv =
  "full_name,email_addr,joined_on,plan,country\n" +
  ["IN", "IN", "IN", ""]
    .map(
      (country, index) =>
        `Profile Person ${index},fixed-profile-${index}@example.com,03/04/2026,${["pro", "basic", "enterprise", "pro"][index]},${country}\n`,
    )
    .join("");
const sourceFiles = [
  "agents",
  "domain",
  "local_provider",
  "profiling",
  "retrieval",
].map((name) => `backend/app/${name}.py`);
const sourceHash = createHash("sha256");
for (const file of sourceFiles)
  sourceHash.update(file).update(readFileSync(file));
const results = {
  source_digest: sourceHash.digest("hex"),
  fixed_csv: fixedCsv,
  model_manifest: await (await fetch("http://127.0.0.1:11434/api/tags")).json(),
  units: "milliseconds, monotonic performance.now",
  warmup: null,
  repetitions: [],
};
for (let index = 0; index < 4; index++) {
  const form = new FormData();
  form.append(
    "file",
    new Blob([fixedCsv], { type: "text/csv" }),
    "fixed-latency-profile.csv",
  );
  const uploadResponse = await fetch("http://localhost:5173/api/uploads", {
    method: "POST",
    headers,
    body: form,
  });
  if (!uploadResponse.ok)
    throw new Error(`Upload failed ${uploadResponse.status}`);
  const upload = await uploadResponse.json();
  const started = performance.now();
  const response = await fetch(
    `http://localhost:5173/api/uploads/${upload.id}/suggest`,
    { method: "POST", headers },
  );
  const value = await response.json();
  const wallMs = performance.now() - started;
  if (!response.ok) {
    writeFileSync(
      output,
      JSON.stringify({ ...results, failure: value }, null, 2),
    );
    throw new Error(`Suggestion failed ${response.status}`);
  }
  const record = {
    index,
    request_wall_ms: Math.round(wallMs * 1000) / 1000,
    run: value.agent_run,
  };
  if (index === 0) results.warmup = record;
  else results.repetitions.push(record);
  writeFileSync(output, JSON.stringify(results, null, 2));
  console.log(
    JSON.stringify({
      index,
      wall_ms: record.request_wall_ms,
      workflow_ms: record.run.duration_ms,
      calls: record.run.calls.map((call) => ({
        agent: call.agent,
        duration_ms: call.duration_ms,
        spans: call.spans,
      })),
    }),
  );
}
const walls = results.repetitions
  .map((row) => row.request_wall_ms)
  .sort((a, b) => a - b);
results.median_request_wall_ms = walls[1];
writeFileSync(output, JSON.stringify(results, null, 2));
