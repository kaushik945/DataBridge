import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  FolderClock,
  GitBranch,
  LogOut,
  Plus,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from "lucide-react";
import type {
  Customer,
  Evidence,
  FieldName,
  Mapping,
  Row,
  Rule,
  Upload,
} from "./types";
import "./style.css";

const fields: FieldName[] = [
  "name",
  "email",
  "signup_date",
  "subscription_tier",
  "country_code",
];
let csrf = "";
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 600000);
  try {
    const response = await fetch("/api" + path, {
      ...options,
      credentials: "include",
      signal: controller.signal,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        "X-CSRF-Token": csrf,
        ...options.headers,
      },
    });
    if (!response.ok) {
      const error = await response
        .json()
        .catch(() => ({ detail: "Request failed" }));
      throw new Error(
        typeof error.detail === "string"
          ? error.detail
          : "Check your inputs and try again",
      );
    }
    return (await response.json()) as T;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError")
      throw new Error("Request timed out. Retry or use manual mapping.");
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  ...(body ? { body: JSON.stringify(body) } : {}),
});
function App() {
  const [user, setUser] = useState<{ username: string; mode: string } | null>(
      null,
    ),
    [checking, setChecking] = useState(true);
  const [view, setView] = useState("imports"),
    [uploads, setUploads] = useState<Upload[]>([]),
    [selected, setSelected] = useState<Upload | null>(null);
  const approvalConcerns = selected?.agent_run?.findings
    ? selected.agent_run.findings.filter(
        (f) =>
          f.origin === "model_concern" || f.origin === "documentation_conflict",
      )
    : [
        ...new Set(
          [
            ...(selected?.agent_run?.investigator_findings || []),
            ...(selected?.agent_run?.review?.findings || []),
          ].map((f) => (typeof f === "string" ? f : f.explanation)),
        ),
      ].map((explanation) => ({ field: "file", explanation }));
  const [mapping, setMapping] = useState<Mapping>({ rules: [] }),
    [dirty, setDirty] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const [invalidCategories, setInvalidCategories] = useState<
    Record<string, boolean>
  >({});
  const invalidMapping = Object.values(invalidCategories).some(Boolean);
  const [rows, setRows] = useState<Row[]>([]),
    [page, setPage] = useState(1),
    [rowTotal, setRowTotal] = useState(0),
    [filter, setFilter] = useState("all");
  const [customers, setCustomers] = useState<Customer[]>([]),
    [customerTotal, setCustomerTotal] = useState(0),
    [customerPage, setCustomerPage] = useState(1);
  const [evidence, setEvidence] = useState<Evidence | null>(null),
    [confirmation, setConfirmation] = useState(false);
  useEffect(() => {
    if (!evidence && !confirmation) return;
    const previous = document.activeElement as HTMLElement | null;
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setEvidence(null);
        setConfirmation(false);
      }
      if (event.key === "Tab") {
        const controls = Array.from(
          document.querySelectorAll<HTMLElement>(
            '[role="dialog"] button:not(:disabled), [role="dialog"] a[href]',
          ),
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard);
      previous?.focus();
    };
  }, [evidence, confirmation]);
  useEffect(() => {
    api<{ username: string; csrf: string; mode: string }>("/session")
      .then((s) => {
        csrf = s.csrf;
        setUser(s);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  async function refresh() {
    setUploads(await api<Upload[]>("/uploads"));
  }
  useEffect(() => {
    if (user) void refresh().catch((e) => setError(e.message));
  }, [user]);
  useEffect(() => {
    if (!selected) return;
    api<{ rows: Row[]; total: number }>(
      `/uploads/${selected.id}/rows?page=${page}&status=${filter}`,
    )
      .then((r) => {
        setRows(r.rows);
        setRowTotal(r.total);
      })
      .catch((e) => setError(e.message));
  }, [selected, page, filter]);
  useEffect(() => {
    if (user && view === "customers")
      api<{ rows: Customer[]; total: number }>(
        `/customers?page=${customerPage}`,
      )
        .then((r) => {
          setCustomers(r.rows);
          setCustomerTotal(r.total);
        })
        .catch((e) => setError(e.message));
  }, [user, view, customerPage]);
  function select(u: Upload) {
    setInvalidCategories({});
    setSelected(u);
    setMapping(structuredClone(u.mapping));
    setDirty(false);
    setPage(1);
    setFilter("all");
    setError("");
  }
  async function action(label: string, work: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy("");
    }
  }
  async function mutate(suffix: string, body?: unknown) {
    if (!selected) return;
    const u = await api<Upload>(
      `/uploads/${selected.id}/${suffix}`,
      post(body),
    );
    select(u);
    await refresh();
  }
  function update(destination: FieldName, patch: Partial<Rule>) {
    if ("source" in patch) {
      setInvalidCategories((values) => ({ ...values, [destination]: false }));
    }
    setMapping((m) => {
      const old = m.rules.find((r) => r.destination === destination);
      return {
        rules: [
          ...m.rules.filter((r) => r.destination !== destination),
          {
            destination,
            source: "",
            trim: true,
            date_format: null,
            categories: {},
            citations: [],
            ...old,
            ...patch,
          },
        ].filter((r) => r.source),
      };
    });
    setDirty(true);
  }
  if (checking)
    return (
      <main className="login">
        <div className="brand">
          <GitBranch /> DataBridge
        </div>
        <p>Connecting to your workspace…</p>
      </main>
    );
  if (!user)
    return (
      <main className="login">
        <div className="login-card">
          <div className="brand">
            <span className="brandmark">
              <GitBranch size={23} />
            </span>{" "}
            DataBridge
          </div>
          <div className="eyebrow">NORTHSTAR / CUSTOMER OPERATIONS</div>
          <h1>Good data starts here.</h1>
          <p>
            Sign in to review, validate, and safely import your customer data.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void action("Signing in", async () => {
                const s = await api<{
                  username: string;
                  csrf: string;
                  mode: string;
                }>("/login", post(Object.fromEntries(data)));
                csrf = s.csrf;
                setUser(s);
              });
            }}
          >
            <label>
              Username
              <input name="username" autoComplete="username" required />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            {error && (
              <div role="alert" className="error">
                {error}
              </div>
            )}
            <button className="primary" disabled={!!busy}>
              {busy || "Sign in"} <ArrowRight size={17} />
            </button>
          </form>
          <small>
            One operator. Explicit approval. Every import accounted for.
          </small>
        </div>
        <div className="login-art">
          <GitBranch size={150} strokeWidth={0.65} />
          <h2>
            From messy files
            <br />
            to trusted records.
          </h2>
          <p>Human judgment, assisted by AI.</p>
        </div>
      </main>
    );
  const step = !selected
    ? 0
    : selected.state === "IMPORTED"
      ? 3
      : ["VALIDATED", "APPROVED"].includes(selected.state)
        ? 2
        : 1;
  return (
    <div className="shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault();
            setSelected(null);
            setView("imports");
          }}
        >
          <span className="brandmark">
            <GitBranch size={22} />
          </span>
          DataBridge
        </a>
        <div className="workspace">
          <span className="workspace-icon">N</span>
          <div>
            <strong>Northstar</strong>
            <small>Customer operations</small>
          </div>
          <span className="workspace-dot" />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          <button
            className={view === "imports" ? "active" : ""}
            onClick={() => {
              setView("imports");
              setSelected(null);
            }}
          >
            <UploadCloud size={18} />
            Customer imports
          </button>
          <button
            className={view === "customers" ? "active" : ""}
            onClick={() => setView("customers")}
          >
            <Database size={18} />
            Customer records
          </button>
          <button
            className={view === "history" ? "active" : ""}
            onClick={() => {
              setView("history");
              void refresh();
            }}
          >
            <FolderClock size={18} />
            Import history
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="assurance">
            <ShieldCheck size={19} />
            <strong>You’re in control</strong>
            <p>Nothing is imported without your explicit approval.</p>
          </div>
          <div className="user">
            <span className="avatar">{user.username[0].toUpperCase()}</span>
            <div>
              <strong>{user.username}</strong>
              <small>Operator</small>
            </div>
            <button
              aria-label="Sign out"
              onClick={() =>
                void action("Signing out", async () => {
                  await api("/logout", post());
                  setUser(null);
                  setSelected(null);
                })
              }
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            <strong>
              {view === "customers"
                ? "Customer records"
                : view === "history"
                  ? "Import history"
                  : "Customer imports"}
            </strong>
          </span>
          <span className="mode">
            <span />{" "}
            {user.mode === "mock"
              ? "Mock mode · Local demo"
              : user.mode === "local"
                ? "Local AI"
                : "Vertex AI mode"}
          </span>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">CUSTOMER DATA ONBOARDING</div>
              <h1>
                {view === "customers"
                  ? "Your customer records"
                  : view === "history"
                    ? "Every import, accounted for"
                    : selected
                      ? "Review your import"
                      : "A clean start for your data"}
              </h1>
              <p>
                {view === "customers"
                  ? "Validated records imported into Northstar."
                  : view === "history"
                    ? "Review past files, decisions, and results."
                    : "Turn a messy CSV into validated customer records, one clear step at a time."}
              </p>
            </div>
            {selected && view === "imports" && (
              <button
                className="secondary"
                onClick={() => {
                  setSelected(null);
                  setError("");
                }}
              >
                <Plus size={16} />
                New import
              </button>
            )}
          </div>
          {error && (
            <div className="error" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {busy && (
            <div role="status" className="busy">
              <span className="spinner" />
              {busy}…
            </div>
          )}
          {view === "imports" && (
            <>
              <div className="steps">
                {[
                  "Upload file",
                  "Review mapping",
                  "Validate & approve",
                  "Import complete",
                ].map((label, i) => (
                  <React.Fragment key={label}>
                    <div
                      className={
                        i === step
                          ? "step current"
                          : i < step
                            ? "step done"
                            : "step"
                      }
                    >
                      <span>
                        {i < step ? (
                          <Check size={14} />
                        ) : (
                          String(i + 1).padStart(2, "0")
                        )}
                      </span>
                      {label}
                    </div>
                    {i < 3 && <div className="step-line" />}
                  </React.Fragment>
                ))}
              </div>
              {!selected ? (
                <>
                  <section className="card upload-card">
                    <div className="section-title">
                      <span className="icon-box">
                        <UploadCloud size={20} />
                      </span>
                      <div>
                        <h2>Bring your customer data</h2>
                        <p>
                          Start with a CSV. We’ll help you take it from here.
                        </p>
                      </div>
                      <span className="pill">CSV ONLY</span>
                    </div>
                    <label
                      className="dropzone"
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        const f = e.dataTransfer.files[0];
                        if (f)
                          void action("Uploading file", async () => {
                            const data = new FormData();
                            data.append("file", f);
                            select(
                              await api<Upload>("/uploads", {
                                method: "POST",
                                body: data,
                              }),
                            );
                            await refresh();
                          });
                      }}
                    >
                      <input
                        aria-label="Upload CSV"
                        type="file"
                        accept=".csv,text/csv"
                        disabled={!!busy}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f)
                            void action("Uploading file", async () => {
                              const data = new FormData();
                              data.append("file", f);
                              select(
                                await api<Upload>("/uploads", {
                                  method: "POST",
                                  body: data,
                                }),
                              );
                              await refresh();
                            });
                        }}
                      />
                      <div className="upload-symbol">
                        <UploadCloud size={29} strokeWidth={1.6} />
                      </div>
                      <h3>Drop your CSV file here</h3>
                      <p>
                        or <span>browse files</span> to get started
                      </p>
                      <small>UTF-8 CSV · Up to 5 MB · 10,000 rows</small>
                    </label>
                    <div className="upload-footer">
                      <ShieldCheck size={16} />
                      <span>
                        Your original file stays intact. Review every change
                        before importing.
                      </span>
                    </div>
                  </section>
                  <div className="intro-grid">
                    <div>
                      <span className="mini-number">01</span>
                      <h3>Map with context</h3>
                      <p>
                        Connect your columns to the customer schema, with
                        documentation alongside.
                      </p>
                    </div>
                    <div>
                      <span className="mini-number">02</span>
                      <h3>Catch issues early</h3>
                      <p>
                        Preview transformations and find invalid rows before
                        they reach your database.
                      </p>
                    </div>
                    <div>
                      <span className="mini-number">03</span>
                      <h3>Approve with confidence</h3>
                      <p>
                        Choose to import valid rows and keep a clear report of
                        anything rejected.
                      </p>
                    </div>
                  </div>
                  <section className="card recent">
                    <div className="card-heading">
                      <h2>
                        Recent imports{" "}
                        <span className="count">{uploads.length}</span>
                      </h2>
                      <button
                        className="text-button"
                        onClick={() => setView("history")}
                      >
                        View history <ArrowUpRight size={15} />
                      </button>
                    </div>
                    {uploads.length ? (
                      <History
                        uploads={uploads.slice(0, 5)}
                        onSelect={(u) => select(u)}
                      />
                    ) : (
                      <div className="empty">
                        <FolderClock size={26} />
                        <h3>Your first import starts above</h3>
                        <p>
                          Uploaded files and their results will appear here.
                        </p>
                      </div>
                    )}
                  </section>
                </>
              ) : (
                <>
                  <div className="file-bar">
                    <span className="file-icon">
                      <FileText size={23} />
                    </span>
                    <div>
                      <strong>{selected.filename}</strong>
                      <small>
                        {selected.row_count.toLocaleString()} rows ·{" "}
                        {selected.headers.length} columns · Mapping v
                        {selected.version}
                      </small>
                    </div>
                    <span className="status">
                      {selected.state.replaceAll("_", " ")}
                    </span>
                  </div>
                  <section className="card">
                    <div className="card-heading">
                      <div>
                        <h2>Column mapping</h2>
                        <p>
                          Choose a source for each destination field. Unmapped
                          columns are excluded.
                        </p>
                      </div>
                      <button
                        className="secondary"
                        disabled={!!busy || selected.state === "IMPORTED"}
                        onClick={() =>
                          void action("Generating suggestions", () =>
                            mutate("suggest"),
                          )
                        }
                      >
                        <Sparkles size={16} />
                        {selected.agent_run
                          ? "Regenerate suggestions"
                          : "Suggest mapping"}
                      </button>
                    </div>
                    <div className="table-scroll">
                      <table className="mapping-table">
                        <thead>
                          <tr>
                            <th>DESTINATION FIELD</th>
                            <th>SOURCE COLUMN</th>
                            <th>TRANSFORMATION</th>
                            <th>REVIEW & EVIDENCE</th>
                          </tr>
                        </thead>
                        <tbody>
                          {fields.map((f) => {
                            const r = mapping.rules.find(
                              (x) => x.destination === f,
                            );
                            return (
                              <tr key={f}>
                                <td>
                                  <code>{f}</code>
                                  <small>
                                    {f === "country_code"
                                      ? "Optional"
                                      : "Required"}
                                  </small>
                                </td>
                                <td>
                                  <select
                                    aria-label={`${f} source`}
                                    value={r?.source || ""}
                                    disabled={
                                      selected.state === "IMPORTED" || !!busy
                                    }
                                    onChange={(e) =>
                                      update(f, {
                                        source: e.target.value,
                                        citations: [],
                                      })
                                    }
                                  >
                                    <option value="">Select column…</option>
                                    {selected.headers.map((h) => (
                                      <option key={h}>{h}</option>
                                    ))}
                                  </select>
                                </td>
                                <td>
                                  {r && (
                                    <>
                                      <label className="checkbox">
                                        <input
                                          type="checkbox"
                                          checked={r.trim}
                                          disabled={
                                            selected.state === "IMPORTED"
                                          }
                                          onChange={(e) =>
                                            update(f, {
                                              trim: e.target.checked,
                                            })
                                          }
                                        />
                                        Trim whitespace
                                      </label>
                                      {f === "signup_date" && (
                                        <select
                                          aria-label="Date format"
                                          value={r.date_format || ""}
                                          disabled={
                                            selected.state === "IMPORTED"
                                          }
                                          onChange={(e) =>
                                            update(f, {
                                              date_format:
                                                e.target.value || null,
                                            })
                                          }
                                        >
                                          <option value="">
                                            Human date selection required
                                          </option>
                                          <option value="%Y-%m-%d">
                                            YYYY-MM-DD
                                          </option>
                                          <option value="%d/%m/%Y">
                                            DD/MM/YYYY
                                          </option>
                                          <option value="%m/%d/%Y">
                                            MM/DD/YYYY
                                          </option>
                                          <option value="%d-%m-%Y">
                                            DD-MM-YYYY
                                          </option>
                                        </select>
                                      )}
                                      {(f === "subscription_tier" ||
                                        f === "country_code") && (
                                        <CategoryEditor
                                          key={`${selected.id}-${selected.version}-${f}`}
                                          value={r.categories}
                                          onValidity={(valid) =>
                                            setInvalidCategories((v) => ({
                                              ...v,
                                              [f]: !valid,
                                            }))
                                          }
                                          disabled={
                                            selected.state === "IMPORTED"
                                          }
                                          onChange={(categories) =>
                                            update(f, {
                                              categories,
                                              citations: [],
                                            })
                                          }
                                        />
                                      )}
                                    </>
                                  )}
                                </td>
                                <td>
                                  <span className={r ? "review-tag" : "muted"}>
                                    {r ? "Human review required" : "Unmapped"}
                                  </span>
                                  {r?.citations.map((c) => (
                                    <button
                                      key={c}
                                      className="citation"
                                      onClick={() =>
                                        void action(
                                          "Opening evidence",
                                          async () =>
                                            setEvidence(
                                              await api<Evidence>(
                                                `/evidence/${c}`,
                                              ),
                                            ),
                                        )
                                      }
                                    >
                                      <FileText size={12} />
                                      View source
                                    </button>
                                  ))}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="card-actions">
                      <small>
                        {dirty
                          ? "Unsaved changes · saving will invalidate validation and approval"
                          : "Only allowlisted transformations can run."}
                      </small>
                      <button
                        className="secondary"
                        disabled={
                          invalidMapping ||
                          !dirty ||
                          !!busy ||
                          selected.state === "IMPORTED"
                        }
                        onClick={() =>
                          void action("Saving mapping", async () => {
                            const u = await api<Upload>(
                              `/uploads/${selected.id}/mapping`,
                              { method: "PUT", body: JSON.stringify(mapping) },
                            );
                            select(u);
                            await refresh();
                          })
                        }
                      >
                        Save mapping
                      </button>
                      <button
                        className="primary"
                        disabled={
                          invalidMapping ||
                          dirty ||
                          !selected.version ||
                          !!busy ||
                          selected.state === "IMPORTED"
                        }
                        onClick={() =>
                          void action("Validating all rows", () =>
                            mutate("validate"),
                          )
                        }
                      >
                        Validate all rows <ArrowRight size={15} />
                      </button>
                    </div>
                  </section>
                  {selected.agent_run && (
                    <details className="card agent-panel" open>
                      <summary>
                        <Sparkles size={17} />
                        Agent run{" "}
                        <span className="pill">
                          {selected.agent_run.mode.toUpperCase()}
                        </span>
                        <span className="muted">
                          {selected.agent_run.review
                            ? "Investigator → Reviewer → Human"
                            : "Investigator → Human"}
                        </span>
                      </summary>
                      <div className="agent-body">
                        <div className="agent-meta">
                          <span>
                            Model<strong>{selected.agent_run.model}</strong>
                          </span>
                          <span>
                            {selected.agent_run.mode === "mock"
                              ? "Fixture duration"
                              : "Model workflow duration"}
                            <strong>{selected.agent_run.duration_ms} ms</strong>
                          </span>
                          <span>
                            Tokens (in / out)
                            <strong>
                              {selected.agent_run.usage
                                ? `${selected.agent_run.usage.input_tokens} / ${selected.agent_run.usage.output_tokens}`
                                : "Not applicable"}
                            </strong>
                          </span>
                          <span>
                            Estimated cost
                            <strong>
                              {selected.agent_run.estimated_cost_usd === null
                                ? "Not available"
                                : `$${selected.agent_run.estimated_cost_usd.toFixed(6)}`}
                            </strong>
                          </span>
                        </div>
                        <p>
                          {selected.agent_run.disclaimer ||
                            `Pricing date: ${selected.agent_run.pricing_date || "not configured"}`}
                        </p>
                        <strong>
                          Review:{" "}
                          {(
                            selected.agent_run.status ||
                            selected.agent_run.review?.status
                          )?.replaceAll("_", " ") || "Not run"}
                        </strong>
                        {selected.agent_run.mapping_version && (
                          <p>
                            Findings for AI mapping v
                            {selected.agent_run.mapping_version}
                            {selected.agent_run.mapping_version !==
                            selected.version
                              ? ` · Current mapping is v${selected.version}. Validate your edits for current results.`
                              : ""}
                          </p>
                        )}
                        {selected.agent_run.findings ? (
                          <ul aria-label="Review findings">
                            {selected.agent_run.findings.map(
                              (finding, index) => (
                                <li key={index}>
                                  <strong>
                                    {finding.field} ·{" "}
                                    {finding.issue_type.replaceAll("_", " ")}
                                  </strong>
                                  <div>
                                    {finding.severity} ·{" "}
                                    {finding.origin.replaceAll("_", " ")} ·{" "}
                                    {finding.scope === "sample"
                                      ? "sample only"
                                      : finding.scope}{" "}
                                    ·{" "}
                                    {finding.verified
                                      ? "verified"
                                      : "unverified"}
                                    {finding.blocking
                                      ? " · action required"
                                      : " · advisory"}
                                  </div>
                                  <p>{finding.explanation}</p>
                                  {finding.validator_ids.map((id) => (
                                    <div key={id}>
                                      Validator result <code>{id}</code>
                                    </div>
                                  ))}
                                  {finding.evidence_ids.map((id) => (
                                    <button
                                      className="text-button"
                                      key={id}
                                      onClick={() => {
                                        const chunk =
                                          selected.agent_run?.evidence.find(
                                            (item) => item.id === id,
                                          );
                                        if (chunk) setEvidence(chunk);
                                      }}
                                    >
                                      View supporting evidence
                                    </button>
                                  ))}
                                </li>
                              ),
                            )}
                          </ul>
                        ) : (
                          <ul aria-label="Historical review notes">
                            {[
                              ...new Set([
                                ...selected.agent_run.investigator_findings,
                                ...selected.agent_run.checks,
                                ...(selected.agent_run.review?.findings || []),
                              ]),
                            ].map((f, i) => (
                              <li key={i}>
                                {typeof f === "string" ? f : f.explanation}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </details>
                  )}
                  <section className="card">
                    <div className="card-heading">
                      <div>
                        <h2>
                          {selected.validation
                            ? "Validation results"
                            : "Original row preview"}
                        </h2>
                        <p>
                          {selected.validation
                            ? "Review before and after values. Every rejected row remains in the error report."
                            : "Your original values, before any transformations."}
                        </p>
                      </div>
                      {selected.validation && (
                        <a
                          className="secondary"
                          href={`/api/uploads/${selected.id}/errors`}
                          download
                        >
                          Download error report
                        </a>
                      )}
                    </div>
                    {selected.validation && (
                      <div className="validation-stats">
                        <div>
                          <span className="stat-dot good" />
                          <strong>{selected.validation.valid}</strong>valid rows
                        </div>
                        <div>
                          <span className="stat-dot bad" />
                          <strong>{selected.validation.invalid}</strong>rejected
                          rows
                        </div>
                        <span className="muted">
                          Deterministic Python validation
                        </span>
                        <select
                          aria-label="Filter rows"
                          value={filter}
                          onChange={(e) => {
                            setFilter(e.target.value);
                            setPage(1);
                          }}
                        >
                          <option value="all">All rows</option>
                          <option value="valid">Valid rows</option>
                          <option value="invalid">Rejected rows</option>
                        </select>
                      </div>
                    )}
                    <div className="table-scroll">
                      <table className="preview-table">
                        <thead>
                          <tr>
                            <th>ROW</th>
                            <th>ORIGINAL VALUES</th>
                            {selected.validation && (
                              <>
                                <th>TRANSFORMED VALUES</th>
                                <th>RESULT</th>
                              </>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {rows.map((row) => (
                            <tr key={row.row_number}>
                              <td className="row-number">{row.row_number}</td>
                              <td>
                                <ValueList values={row.values} />
                              </td>
                              {selected.validation && (
                                <>
                                  <td>
                                    <ValueList values={row.after || {}} />
                                  </td>
                                  <td>
                                    {row.valid ? (
                                      <span className="success-label">
                                        <Check size={13} />
                                        Valid
                                      </span>
                                    ) : (
                                      <ul className="row-errors">
                                        {row.errors?.map((e) => (
                                          <li key={e}>{e}</li>
                                        ))}
                                      </ul>
                                    )}
                                  </td>
                                </>
                              )}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {!rows.length && (
                        <p className="empty">No rows match this filter.</p>
                      )}
                    </div>
                    <Pagination page={page} total={rowTotal} onPage={setPage} />
                  </section>
                  {selected.validation && selected.state !== "IMPORTED" && (
                    <section className="approval-card">
                      <span className="icon-box">
                        <ShieldCheck size={24} />
                      </span>
                      <div>
                        <h2>
                          {selected.state === "APPROVED"
                            ? "Approved and ready to import"
                            : "The final decision is yours"}
                        </h2>
                        <p>
                          {selected.validation.valid} valid rows will be
                          imported. {selected.validation.invalid} rejected rows
                          will stay in a downloadable report.
                        </p>
                        <small>
                          Approval covers file {selected.file_hash.slice(0, 12)}
                          … · mapping v{selected.version} · valid rows only.
                        </small>
                      </div>
                      <div className="approval-buttons">
                        <button
                          className="secondary"
                          disabled={!!busy || dirty}
                          onClick={() =>
                            void action("Cancelling approval", () =>
                              mutate("approve", {
                                version: selected.version,
                                validation_hash: selected.validation!.hash,
                                policy: "cancel",
                              }),
                            )
                          }
                        >
                          Cancel and fix the file
                        </button>
                        <button
                          className="primary"
                          disabled={
                            invalidMapping ||
                            !!busy ||
                            dirty ||
                            !selected.validation.valid
                          }
                          onClick={() => setConfirmation(true)}
                        >
                          {selected.state === "APPROVED"
                            ? "Execute approved import"
                            : "Review import approval"}
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    </section>
                  )}
                  {selected.result && (
                    <div className="import-success">
                      <ShieldCheck size={28} />
                      <div>
                        <h2>Import complete</h2>
                        <p>
                          {selected.result.imported} customers imported.{" "}
                          {selected.result.rejected} rows rejected and retained
                          in your report.
                        </p>
                      </div>
                      <button
                        className="secondary"
                        onClick={() => setView("customers")}
                      >
                        View customer records
                        <ArrowRight size={15} />
                      </button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
          {view === "history" && (
            <section className="card">
              <div className="card-heading">
                <h2>
                  Import history <span className="count">{uploads.length}</span>
                </h2>
                <span className="muted">Most recent 100 files</span>
              </div>
              {uploads.length ? (
                <History
                  uploads={uploads}
                  onSelect={(u) => {
                    select(u);
                    setView("imports");
                  }}
                />
              ) : (
                <p className="empty">
                  No uploads yet. Start a customer import.
                </p>
              )}
            </section>
          )}
          {view === "customers" && (
            <section className="card">
              <div className="card-heading">
                <h2>
                  Customer records{" "}
                  <span className="count">{customerTotal}</span>
                </h2>
                <span className="muted">Northstar destination</span>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>NAME</th>
                      <th>EMAIL</th>
                      <th>SIGNUP DATE</th>
                      <th>TIER</th>
                      <th>COUNTRY</th>
                    </tr>
                  </thead>
                  <tbody>
                    {customers.map((c) => (
                      <tr key={c.id}>
                        <td>{c.name}</td>
                        <td>{c.email}</td>
                        <td>{c.signup_date}</td>
                        <td>
                          <span className="pill">{c.subscription_tier}</span>
                        </td>
                        <td>{c.country_code || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!customers.length && (
                  <div className="empty">
                    <Database size={26} />
                    <h3>A clean slate</h3>
                    <p>Approved imports will add customer records here.</p>
                  </div>
                )}
              </div>
              <Pagination
                page={customerPage}
                total={customerTotal}
                onPage={setCustomerPage}
              />
            </section>
          )}
          <footer>
            <GitBranch size={14} />
            DataBridge<span>Built for careful imports.</span>
            <span className="footer-right">
              <ShieldCheck size={13} />
              Human-approved by design
            </span>
          </footer>
        </main>
      </div>
      {evidence && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="evidence-title"
          >
            <button
              className="close"
              aria-label="Close evidence"
              autoFocus
              onClick={() => setEvidence(null)}
            >
              <X />
            </button>
            <div className="eyebrow">SUPPORTING DOCUMENTATION</div>
            <h2 id="evidence-title">{evidence.title}</h2>
            <p>{evidence.document}</p>
            <blockquote>{evidence.text}</blockquote>
            <small>
              Chunk {evidence.id} · version {evidence.hash.slice(0, 12)}
            </small>
            <button className="secondary" onClick={() => setEvidence(null)}>
              Close source
            </button>
          </section>
        </div>
      )}
      {confirmation && selected?.validation && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="approval-title"
          >
            <button
              className="close"
              aria-label="Close approval"
              onClick={() => setConfirmation(false)}
            >
              <X />
            </button>
            <ShieldCheck className="accent" size={34} />
            <h2 id="approval-title">
              Import {selected.validation.valid} valid customer records?
            </h2>
            <p>
              You are approving the exact validated mapping v{selected.version}{" "}
              for <strong>{selected.filename}</strong>.
            </p>
            <div className="notice">
              {selected.validation.invalid} rejected rows will not be imported.
              Their original values and errors will remain available in the
              rejected-row report.
            </div>
            {approvalConcerns.length > 0 && (
              <div className="notice">
                <strong>Review the advisory concerns before approving.</strong>
                <ul>
                  {approvalConcerns.map((finding, index) => (
                    <li key={index}>
                      {finding.field} · {finding.explanation}
                    </li>
                  ))}
                </ul>
                <p>
                  These concerns refer to AI mapping v
                  {selected.agent_run?.mapping_version || "unknown"}. Confirm
                  your current mapping v{selected.version} addresses them. Ready
                  for human review requires your judgment.
                </p>
              </div>
            )}
            <p>
              Mode: <strong>{selected.mode}</strong> · Policy:{" "}
              <strong>Import only valid rows</strong>
            </p>
            <div className="modal-actions">
              <button
                className="secondary"
                autoFocus
                onClick={() => setConfirmation(false)}
              >
                Back to review
              </button>
              <button
                className="primary"
                disabled={!!busy}
                onClick={() =>
                  void action("Importing approved rows", async () => {
                    let u = selected;
                    if (u.state !== "APPROVED")
                      u = await api<Upload>(
                        `/uploads/${u.id}/approve`,
                        post({
                          version: u.version,
                          validation_hash: u.validation!.hash,
                          policy: "valid_only",
                        }),
                      );
                    select(u);
                    const approvalId = u.approval!.id;
                    await api(
                      `/uploads/${u.id}/import`,
                      post({
                        approval_id: approvalId,
                        idempotency_key: `import-${approvalId}`,
                      }),
                    );
                    select(await api<Upload>(`/uploads/${u.id}`));
                    await refresh();
                    setConfirmation(false);
                  })
                }
              >
                Approve & import
                <ArrowRight size={16} />
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
function ValueList({ values }: { values: Record<string, string | null> }) {
  return (
    <dl className="values">
      {Object.entries(values).map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v || <span className="muted">empty</span>}</dd>
        </div>
      ))}
    </dl>
  );
}
function CategoryEditor({
  value,
  onChange,
  onValidity,
  disabled,
}: {
  value: Record<string, string>;
  onChange: (v: Record<string, string>) => void;
  onValidity: (valid: boolean) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState(JSON.stringify(value)),
    [invalid, setInvalid] = useState(false);
  return (
    <label className="category-label">
      Category pairs (JSON)
      <input
        aria-label="Category pairs"
        disabled={disabled}
        value={text}
        aria-invalid={invalid}
        onChange={(e) => {
          const t = e.target.value;
          setText(t);
          try {
            const parsed = JSON.parse(t);
            if (
              !parsed ||
              Array.isArray(parsed) ||
              typeof parsed !== "object" ||
              Object.values(parsed).some((v) => typeof v !== "string")
            )
              throw Error();
            onChange(parsed);
            setInvalid(false);
            onValidity(true);
          } catch {
            setInvalid(true);
            onValidity(false);
          }
        }}
      />
      {invalid && (
        <small className="danger">
          Use an object of source-to-target strings.
        </small>
      )}
    </label>
  );
}
function History({
  uploads,
  onSelect,
}: {
  uploads: Upload[];
  onSelect: (u: Upload) => void;
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>FILE NAME</th>
            <th>UPLOADED</th>
            <th>ROWS</th>
            <th>STATUS</th>
            <th>RESULT</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {uploads.map((u) => (
            <tr key={u.id}>
              <td>
                <button className="file-link" onClick={() => onSelect(u)}>
                  <FileText size={16} />
                  {u.filename}
                </button>
              </td>
              <td>{new Date(u.created).toLocaleDateString()}</td>
              <td>{u.row_count}</td>
              <td>
                <span className="status">{u.state.replaceAll("_", " ")}</span>
              </td>
              <td>
                {u.result
                  ? `${u.result.imported} imported · ${u.result.rejected} rejected`
                  : "Awaiting review"}
              </td>
              <td>
                <button
                  className="icon-button"
                  aria-label={`Open ${u.filename}`}
                  onClick={() => onSelect(u)}
                >
                  <ArrowUpRight size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Pagination({
  page,
  total,
  onPage,
}: {
  page: number;
  total: number;
  onPage: (p: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${(page - 1) * 25 + 1}–${Math.min(page * 25, total)} of ${total} rows`
          : "0 rows"}
      </span>
      <button
        aria-label="Previous page"
        disabled={page === 1}
        onClick={() => onPage(page - 1)}
      >
        <ChevronLeft size={15} />
      </button>
      <span>Page {page}</span>
      <button
        aria-label="Next page"
        disabled={page * 25 >= total}
        onClick={() => onPage(page + 1)}
      >
        <ChevronRight size={15} />
      </button>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
