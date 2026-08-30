// Purpose: Provides the only browser-to-backend boundary for the loopback v0.2 console.
import type {
  ApiRecord, BuiltinStudyDescriptor, CompatibilityVerification, EventRecord, LLMConfigView,
  LLMRuntimeConfig, LLMStage, ProjectDetail, ProjectSnapshot, ResearchState, RuntimeHealth,
  V01CompatibilityImport
} from "./types";

interface ApiErrorEnvelope {detail?: string | Array<{loc?: Array<string | number>; msg?: string}>}

const configuredApiOrigin = process.env.NEXT_PUBLIC_AUTORESEARCH_V0_2_API_ORIGIN
  ?? "http://127.0.0.1:8100";
const parsedApiOrigin = new URL(configuredApiOrigin);
const loopbackHosts = new Set(["127.0.0.1", "localhost", "::1"]);
if (!loopbackHosts.has(parsedApiOrigin.hostname) || !["http:", "https:"].includes(parsedApiOrigin.protocol)) {
  throw new Error("NEXT_PUBLIC_AUTORESEARCH_V0_2_API_ORIGIN must use an HTTP(S) loopback host");
}
const apiOrigin = parsedApiOrigin.origin;
const backendUrl = (path: string) => `${apiOrigin}${path}`;

function errorMessage(status: number, payload: ApiErrorEnvelope): string {
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail.map(item => [item.loc?.join("."), item.msg].filter(Boolean).join(": ")).join("; ");
  }
  return `请求失败（${status}）`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(backendUrl(path), {...init, headers, cache: "no-store", credentials: "include"});
  if (!response.ok) {
    const payload = await response.json().catch(() => ({detail: response.statusText})) as ApiErrorEnvelope;
    throw new Error(errorMessage(response.status, payload));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function optional<T>(path: string): Promise<T | null> {
  try { return await request<T>(path); }
  catch (error) {
    if (error instanceof Error && error.message.toLowerCase().includes("not found")) return null;
    throw error;
  }
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) => request<T>(path, {
  method: "POST", body: body === undefined ? undefined : JSON.stringify(body)
});

function encodedFilePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export const artifactUrl = {
  imported: (projectId: string, importId: string, path: string) =>
    backendUrl(`/api/projects/${projectId}/imports/${importId}/files/${encodedFilePath(path)}`),
  experiment: (projectId: string, artifactId: string) =>
    backendUrl(`/api/projects/${projectId}/artifacts/${artifactId}/content`),
  analysis: (projectId: string, artifactId: string) =>
    backendUrl(`/api/projects/${projectId}/analysis-artifacts/${artifactId}/content`),
  paper: (projectId: string, paperId: string, artifactId: string) =>
    backendUrl(`/api/projects/${projectId}/papers/${paperId}/artifacts/${artifactId}/content`)
};

export const api = {
  health: () => get<RuntimeHealth>("/health"),
  listProjects: () => get<ProjectDetail[]>("/api/projects"),
  createProject: (payload: unknown) => post<ProjectDetail>("/api/projects", payload),
  getState: (projectId: string) => get<ResearchState>(`/api/projects/${projectId}/state`),
  reconcileWorkflow: (projectId: string) => post<ApiRecord>(`/api/projects/${projectId}/workflow/reconcile`),
  importProject: (projectId: string, sourceRoot: string) => post<ApiRecord>(`/api/projects/${projectId}/imports`, {source_root: sourceRoot}),
  listEvents: (projectId: string, cursor = 0, limit = 300) => get<EventRecord[]>(`/api/projects/${projectId}/events?cursor=${cursor}&limit=${limit}`),

  getLLMConfig: () => get<LLMConfigView>("/api/llm/config"),
  saveLLMConfig: (config: LLMRuntimeConfig) => request<LLMConfigView>("/api/llm/config", {method: "PUT", body: JSON.stringify(config)}),
  saveCredential: (providerId: string, apiKey: string) => request<ApiRecord>(`/api/llm/credentials/${encodeURIComponent(providerId)}`, {method: "PUT", body: JSON.stringify({api_key: apiKey})}),
  clearCredential: (providerId: string) => request<ApiRecord>(`/api/llm/credentials/${encodeURIComponent(providerId)}`, {method: "DELETE"}),
  testConnection: (stage: LLMStage) => post<ApiRecord>("/api/llm/connection-tests", {stage}),
  getUsage: () => get<ApiRecord>("/api/llm/usage"),

  listBuiltins: () => get<BuiltinStudyDescriptor[]>("/api/builtins"),
  listV01CompatibilityImports: () => get<V01CompatibilityImport[]>("/api/compatibility/v0.1/imports"),
  importV01WeightDecay: () => post<V01CompatibilityImport>("/api/compatibility/v0.1/imports/weight-decay-v1"),
  verifyV01CompatibilityImport: (importId: string) => post<CompatibilityVerification>(
    `/api/compatibility/v0.1/imports/${encodeURIComponent(importId)}/verify`
  ),

  understand: (projectId: string, payload: unknown) => post<ApiRecord>(`/api/projects/${projectId}/understanding`, payload),
  runLiterature: (projectId: string, allowNetwork: boolean | null) => post<ApiRecord>(`/api/projects/${projectId}/literature`, {allow_network: allowNetwork}),
  generateHypotheses: (projectId: string, parentRevisionId: string | null, feedback: string[]) => post<ApiRecord>(`/api/projects/${projectId}/hypotheses`, {parent_revision_id: parentRevisionId, feedback}),
  decideHypothesis: (projectId: string, revisionId: string, payload: unknown) => post<ApiRecord>(`/api/projects/${projectId}/hypotheses/${revisionId}/decision`, payload),
  generatePlan: (projectId: string, hypothesisRevisionId: string, parentRevisionId: string | null, feedback: string[]) => post<ApiRecord>(`/api/projects/${projectId}/experiment-plans`, {hypothesis_revision_id: hypothesisRevisionId, parent_revision_id: parentRevisionId, feedback}),
  decidePlan: (projectId: string, revisionId: string, payload: unknown) => post<ApiRecord>(`/api/projects/${projectId}/experiment-plans/${revisionId}/decision`, payload),
  decideProfile: (projectId: string, profileId: string, approved: boolean, feedback: string) => post<ApiRecord>(`/api/projects/${projectId}/visualization-profiles/${profileId}/decision`, {approved, feedback}),
  createFigureSpec: (projectId: string, payload: unknown) => post<ApiRecord>(`/api/projects/${projectId}/figure-specs`, payload),
  createStudy: (projectId: string, payload: unknown) => post<ApiRecord>(`/api/projects/${projectId}/studies`, payload),
  createRun: (projectId: string, studyId: string, runSpecId: string, smoke: boolean) => post<ApiRecord>(`/api/projects/${projectId}/studies/${studyId}/runs`, {run_spec_id: runSpecId, smoke}),
  controlRun: (projectId: string, runId: string, action: "pause" | "resume" | "cancel") => post<ApiRecord>(`/api/projects/${projectId}/runs/${runId}/${action}`),
  createAnalysis: (projectId: string, studyId: string) => post<ApiRecord>(`/api/projects/${projectId}/studies/${studyId}/analyses`),
  verifyAnalysis: (projectId: string, analysisId: string) => post<ApiRecord>(`/api/projects/${projectId}/analyses/${analysisId}/verifications`),
  createScientificReview: (projectId: string, analysisId: string, verificationId: string) => post<ApiRecord>(`/api/projects/${projectId}/analyses/${analysisId}/scientific-reviews`, {verification_id: verificationId}),
  createResearchReview: (projectId: string, analysisId: string, scientificReviewId: string | null) => post<ApiRecord>(`/api/projects/${projectId}/analyses/${analysisId}/research-reviews`, {scientific_review_id: scientificReviewId, claims: []}),
  applyResearchReview: (projectId: string, reviewRunId: string, stateRevision: number) => post<ApiRecord>(`/api/projects/${projectId}/research-reviews/${reviewRunId}/apply`, {expected_state_revision: stateRevision}),
  createPaper: (projectId: string, reviewRunId: string, stateRevision: number, target: string) => post<ApiRecord>(`/api/projects/${projectId}/papers`, {
    research_review_run_id: reviewRunId,
    config: {target, max_parallel_agents: 2, max_review_revisions: 2},
    expected_state_revision: stateRevision
  })
};

export async function loadProjectSnapshot(projectId: string): Promise<ProjectSnapshot> {
  const [state, imports, jobs, events, understanding, understandingHistory, lineage,
    visualizationProfiles, figureSpecs, literatureMatrix, literatureHistory, literatureAttempts,
    literatureSources, literatureEvidence, literatureGaps, literatureReviews, literatureAgentRuns,
    hypotheses, plans, planningReviews, planningApprovals, planningAgentRuns, implementations,
    studies, reviewRecords, paperRecords, experimentAgentRuns, analysisAgentRuns,
    researchReviewAgentRuns, paperAgentRuns] = await Promise.all([
    get<ResearchState>(`/api/projects/${projectId}/state`),
    get<ApiRecord[]>(`/api/projects/${projectId}/imports`),
    get<ApiRecord[]>(`/api/projects/${projectId}/jobs`),
    get<EventRecord[]>(`/api/projects/${projectId}/events?cursor=0&limit=300`),
    optional<ApiRecord>(`/api/projects/${projectId}/understanding`),
    get<ApiRecord[]>(`/api/projects/${projectId}/understanding/history`),
    get<ApiRecord[]>(`/api/projects/${projectId}/code-lineage`),
    get<ApiRecord[]>(`/api/projects/${projectId}/visualization-profiles`),
    get<ApiRecord[]>(`/api/projects/${projectId}/figure-specs`),
    optional<ApiRecord>(`/api/projects/${projectId}/literature`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/history`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/search-attempts`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/sources`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/evidence`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/gaps`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/reviews`),
    get<ApiRecord[]>(`/api/projects/${projectId}/literature/agent-runs`),
    get<ApiRecord[]>(`/api/projects/${projectId}/hypotheses`),
    get<ApiRecord[]>(`/api/projects/${projectId}/experiment-plans`),
    get<ApiRecord[]>(`/api/projects/${projectId}/planning/reviews`),
    get<ApiRecord[]>(`/api/projects/${projectId}/planning/approvals`),
    get<ApiRecord[]>(`/api/projects/${projectId}/planning/agent-runs`),
    get<ApiRecord[]>(`/api/projects/${projectId}/implementation-revisions`),
    get<ApiRecord[]>(`/api/projects/${projectId}/studies`),
    get<ApiRecord[]>(`/api/projects/${projectId}/research-reviews`),
    get<ApiRecord[]>(`/api/projects/${projectId}/papers`),
    get<ApiRecord[]>(`/api/projects/${projectId}/experiment-agent-runs`),
    get<ApiRecord[]>(`/api/projects/${projectId}/analysis-agent-runs`),
    get<ApiRecord[]>(`/api/projects/${projectId}/research-review-agent-runs`),
    get<ApiRecord[]>(`/api/projects/${projectId}/paper-agent-runs`)
  ]);

  const context = understanding && typeof understanding.context === "object" ? understanding.context as ApiRecord : null;
  const contextId = typeof context?.context_id === "string" ? context.context_id : null;
  const reuseAssessment = contextId && context?.mode === "existing_project"
    ? await optional<ApiRecord>(`/api/projects/${projectId}/understanding/${contextId}/reuse-assessment`)
    : null;

  const implementationDiffs = await Promise.all(implementations.map(item =>
    get<ApiRecord>(`/api/projects/${projectId}/implementation-revisions/${String(item.implementation_revision_id)}/diff`)
  ));
  const latestPlan = plans.at(-1);
  const formalGate = latestPlan
    ? await optional<ApiRecord>(`/api/projects/${projectId}/experiment-plans/${String(latestPlan.plan_revision_id)}/formal-experiment-gate`)
    : null;
  const runLists = await Promise.all(studies.map(study =>
    get<ApiRecord[]>(`/api/projects/${projectId}/studies/${String(study.study_id)}/runs`)
  ));
  const runs = await Promise.all(runLists.flat().map(async run => {
    const runId = String(run.run_id);
    const [detail, logs] = await Promise.all([
      get<{run: ApiRecord; artifacts: ApiRecord[]}>(`/api/projects/${projectId}/runs/${runId}`),
      optional<{run_id: string; stdout: string; stderr: string; truncated: boolean}>(`/api/projects/${projectId}/runs/${runId}/logs`)
    ]);
    return {...detail, logs};
  }));
  const analysisLists = await Promise.all(studies.map(study =>
    get<ApiRecord[]>(`/api/projects/${projectId}/studies/${String(study.study_id)}/analyses`)
  ));
  const analyses = await Promise.all(analysisLists.flat().map(async analysis => {
    const analysisId = String(analysis.analysis_id);
    const [artifacts, verifications, scientificReviews, evidenceClaims] = await Promise.all([
      get<ApiRecord[]>(`/api/projects/${projectId}/analyses/${analysisId}/artifacts`),
      get<ApiRecord[]>(`/api/projects/${projectId}/analyses/${analysisId}/verifications`),
      get<ApiRecord[]>(`/api/projects/${projectId}/analyses/${analysisId}/scientific-reviews`),
      get<ApiRecord[]>(`/api/projects/${projectId}/analyses/${analysisId}/evidence-claims`)
    ]);
    return {analysis, artifacts, verifications, scientificReviews, evidenceClaims};
  }));
  const researchReviews = await Promise.all(reviewRecords.map(item =>
    get<ApiRecord>(`/api/projects/${projectId}/research-reviews/${String(item.review_run_id)}`)
  ));
  const papers = await Promise.all(paperRecords.map(item =>
    get<ApiRecord>(`/api/projects/${projectId}/papers/${String(item.paper_id)}`)
  ));
  return {
    state, imports, jobs, events, understanding, understandingHistory, reuseAssessment, lineage,
    visualizationProfiles, figureSpecs,
    literature: {matrix: literatureMatrix, history: literatureHistory, attempts: literatureAttempts,
      sources: literatureSources, evidence: literatureEvidence, gaps: literatureGaps,
      reviews: literatureReviews, agentRuns: literatureAgentRuns},
    hypotheses, plans, formalGate, planningReviews, planningApprovals, planningAgentRuns,
    implementations, implementationDiffs, studies, runs, analyses, researchReviews, papers,
    agentRuns: [...literatureAgentRuns, ...planningAgentRuns, ...experimentAgentRuns,
      ...analysisAgentRuns, ...researchReviewAgentRuns, ...paperAgentRuns]
  };
}
