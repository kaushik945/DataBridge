export type FieldName =
  | "name"
  | "email"
  | "signup_date"
  | "subscription_tier"
  | "country_code";
export type Rule = {
  destination: FieldName;
  source: string;
  trim: boolean;
  date_format: string | null;
  categories: Record<string, string>;
  citations: string[];
};
export type Mapping = { rules: Rule[] };
export type Evidence = {
  id: string;
  title: string;
  text: string;
  document: string;
  hash: string;
};
export type AgentRun = {
  mode: string;
  model: string;
  duration_ms: number;
  usage: { input_tokens: number; output_tokens: number } | null;
  estimated_cost_usd: number | null;
  pricing_date: string | null;
  mapping_version?: number;
  status?: string;
  findings?: ReviewFinding[];
  investigator_findings: (string | ModelFinding)[];
  checks: string[];
  review: { status: string; findings: (string | ModelFinding)[] } | null;
  evidence: Evidence[];
  disclaimer: string | null;
};
export type ModelFinding = {
  field: FieldName | "file";
  issue_type: string;
  severity: "info" | "warning" | "error";
  explanation: string;
  evidence_ids: string[];
  validator_ids: string[];
  scope: string;
};
export type ReviewFinding = ModelFinding & {
  origin:
    | "validator"
    | "human_clarification"
    | "model_concern"
    | "documentation_conflict";
  verified: boolean;
  blocking: boolean;
};
export type Row = {
  row_number: number;
  values: Record<string, string>;
  after?: Record<string, string | null>;
  valid?: boolean;
  errors?: string[];
};
export type Upload = {
  id: string;
  filename: string;
  file_hash: string;
  created: string;
  state: string;
  headers: string[];
  row_count: number;
  samples: Row[];
  version: number;
  mapping: Mapping;
  validation: {
    valid: number;
    invalid: number;
    hash: string;
    mode: string;
  } | null;
  approval: { id: string; policy: string; version: number } | null;
  result: { imported: number; rejected: number } | null;
  agent_run: AgentRun | null;
  mode: string;
};
export type Customer = {
  id: string;
  name: string;
  email: string;
  signup_date: string;
  subscription_tier: string;
  country_code: string | null;
};
