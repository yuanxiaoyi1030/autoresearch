// Purpose: Defines stable frontend contracts for the persisted v0.2 backend resources.
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;
export interface JsonObject {[key: string]: JsonValue | undefined}
export type ApiRecord = Record<string, unknown>;

export type ProjectType = "topic_based" | "existing_project";
export type ResearchStage =
  | "initializing" | "project_understanding" | "literature" | "hypothesis"
  | "wait_hypothesis_approval" | "experiment_planning" | "wait_plan_approval"
  | "experiment_implementation" | "experiment" | "analysis" | "research_review"
  | "report_planning" | "report_writing" | "report_review" | "completed";

export interface ResearchProject extends ApiRecord {
  project_id: string;
  title: string;
  project_type: ProjectType;
  source_root: string | null;
  topic: string | null;
  created_at: string;
  updated_at: string;
}

export interface ResearchState extends ApiRecord {
  project_id: string;
  stage: ResearchStage;
  status: "active" | "waiting_user" | "paused" | "completed" | "failed" | "cancelled";
  current_attempt_id: string | null;
  latest_import_id: string | null;
  outcome: "supported" | "negative_result" | "insufficient_evidence" | null;
  revision: number;
  updated_at: string;
}

export interface ProjectDetail extends ApiRecord {project: ResearchProject; state: ResearchState}

export interface EventRecord extends ApiRecord {
  cursor: number;
  project_id: string;
  event_type: string;
  summary: string;
  stage?: ResearchStage | null;
  payload?: ApiRecord;
  created_at: string;
}

export interface ProviderDescriptor extends ApiRecord {
  provider_type: ProviderType;
  display_name: string;
  available: boolean;
  explicit_offline_only: boolean;
  note?: string | null;
}

export type ProviderType = "openai_compatible" | "openai" | "anthropic" | "gemini" | "local_openai_compatible" | "fake";
export type LLMStage = "project_understanding" | "literature" | "hypothesis_planning" | "experiment_code" | "analysis" | "research_review" | "writer";

export interface ModelRoute {
  model: {
    provider_id: string;
    provider_type: ProviderType;
    model: string;
    base_url: string;
    protocol: "chat_completions" | "responses";
    temperature: number | null;
    max_output_tokens: number;
    timeout_seconds: number;
    retry_count: number;
    credential_required: boolean;
    input_cost_per_million_tokens: number | null;
    output_cost_per_million_tokens: number | null;
  };
  budget: {
    max_calls: number;
    max_input_tokens: number;
    max_output_tokens: number;
    max_total_tokens: number;
    max_cost_usd: number | null;
  };
}

export interface LLMRuntimeConfig {
  default_route: ModelRoute | null;
  stages: Partial<Record<LLMStage, ModelRoute>>;
  offline_mode: boolean;
}

export interface LLMConfigView {
  config: LLMRuntimeConfig;
  status: {status: string; ready: boolean; detail: string; configured_stages: LLMStage[]; credentials: ApiRecord[]};
  providers: ProviderDescriptor[];
}

export interface RunView {
  run: ApiRecord;
  artifacts: ApiRecord[];
  logs: {run_id: string; stdout: string; stderr: string; truncated: boolean} | null;
}

export interface AnalysisView {
  analysis: ApiRecord;
  artifacts: ApiRecord[];
  verifications: ApiRecord[];
  scientificReviews: ApiRecord[];
  evidenceClaims: ApiRecord[];
}

export interface LiteratureView {
  matrix: ApiRecord | null;
  history: ApiRecord[];
  attempts: ApiRecord[];
  sources: ApiRecord[];
  evidence: ApiRecord[];
  gaps: ApiRecord[];
  reviews: ApiRecord[];
  agentRuns: ApiRecord[];
}

export interface ProjectSnapshot {
  state: ResearchState;
  imports: ApiRecord[];
  jobs: ApiRecord[];
  events: EventRecord[];
  understanding: ApiRecord | null;
  understandingHistory: ApiRecord[];
  reuseAssessment: ApiRecord | null;
  lineage: ApiRecord[];
  visualizationProfiles: ApiRecord[];
  figureSpecs: ApiRecord[];
  literature: LiteratureView;
  hypotheses: ApiRecord[];
  plans: ApiRecord[];
  formalGate: ApiRecord | null;
  planningReviews: ApiRecord[];
  planningApprovals: ApiRecord[];
  planningAgentRuns: ApiRecord[];
  implementations: ApiRecord[];
  implementationDiffs: ApiRecord[];
  studies: ApiRecord[];
  runs: RunView[];
  analyses: AnalysisView[];
  researchReviews: ApiRecord[];
  papers: ApiRecord[];
  agentRuns: ApiRecord[];
}

export interface RuntimeHealth extends ApiRecord {
  status: string;
  version: string;
  runtime_root: string;
  host: string;
  conda_env: string | null;
  llm_status: string;
}

export interface BuiltinStudyDescriptor extends ApiRecord {
  builtin_id: "builtin/weight_decay_v1";
  display_name: string;
  legacy_study_id: string;
  source_version: "v0.1";
  execution_mode: "read_only_compatibility_regression";
  evidence_policy: "legacy_hash_verified_not_reproduced";
  expected_conditions: ApiRecord[];
}

export interface V01CompatibilityImport extends ApiRecord {
  compatibility_import_id: string;
  builtin_id: "builtin/weight_decay_v1";
  source_runtime_root: string;
  source_integrity_unchanged: boolean;
  source_manifest_hash: string;
  status: "verified" | "rejected";
  runs: ApiRecord[];
  artifacts: ApiRecord[];
  warnings: string[];
  created_at: string;
}

export interface CompatibilityVerification extends ApiRecord {
  compatibility_import_id: string;
  passed: boolean;
  manifest_exists: boolean;
  manifest_hash_matches: boolean;
  artifact_checks: ApiRecord[];
  findings: string[];
}
