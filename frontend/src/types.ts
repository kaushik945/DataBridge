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
export type CategoryPreview = {
  source_column: string | null;
  recognized_rows: number;
  blank_rows: number;
  rules: {
    before: string;
    after: string;
    evidence_id: string;
    affected_rows: number;
  }[];
  affected_rows: number;
  unresolved: { value: string; rows: number }[];
  unresolved_distinct: number;
  unresolved_rows: number;
  unresolved_truncated: boolean;
  rejected_rules: { value: string; reason: string }[];
  incomplete_validation: string[];
  findings: { id: string; explanation: string; scope: string }[];
};
export type Evidence = {
  id: string;
  title: string;
  text: string;
  document: string;
  hash: string;
};
export type TierSourceProfile = {
  total_rows: number;
  candidates: {
    source: string;
    canonical_rows: number;
    documented_alias_rows: number;
    supported_rows: number;
  }[];
  strong_candidate: string | null;
  truncated: boolean;
};
export type AgentRun = {
  category?: {
    strategy?: string;
    status: string;
    reason: string | null;
    source_profile?: TierSourceProfile;
    source_review_reason?: string;
  };
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
