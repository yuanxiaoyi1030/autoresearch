// Purpose: Exposes the complete persisted A/B research lifecycle as stage-aware UI actions and evidence views.
"use client";

import {useEffect, useMemo, useState} from "react";

import {api, artifactUrl} from "@/lib/api";
import {dateTime, list, numeric, record, records, shortId, text, titleCase} from "@/lib/format";
import type {ApiRecord, ProjectDetail, ProjectSnapshot} from "@/lib/types";
import {AuditJson, Badge, Empty, FormField, InlineNotice, Metric, RecordCard, RecordList, Section} from "./ui";

export type WorkbenchTab = "overview" | "understanding" | "literature" | "planning" | "experiments" | "review" | "paper" | "activity";
const TABS: Array<{id: WorkbenchTab; label: string; index: string}> = [
  {id: "overview", label: "总览", index: "00"}, {id: "understanding", label: "项目理解", index: "01"},
  {id: "literature", label: "文献证据", index: "02"}, {id: "planning", label: "研究设计", index: "03"},
  {id: "experiments", label: "实验与分析", index: "04"}, {id: "review", label: "科研评审", index: "05"},
  {id: "paper", label: "论文", index: "06"}, {id: "activity", label: "活动", index: "07"}
];

const STAGE_TO_TAB: Record<string, WorkbenchTab> = {
  initializing: "overview", project_understanding: "understanding", literature: "literature",
  hypothesis: "planning", wait_hypothesis_approval: "planning", experiment_planning: "planning",
  wait_plan_approval: "planning", experiment_implementation: "experiments", experiment: "experiments",
  analysis: "experiments", research_review: "review", report_planning: "paper",
  report_writing: "paper", report_review: "paper", completed: "paper"
};

type ActionRunner = (label: string, action: () => Promise<unknown>) => Promise<void>;

function latest(items: ApiRecord[]): ApiRecord | null { return items.at(-1) ?? null; }
function id(item: ApiRecord | null, key: string): string { return item && typeof item[key] === "string" ? String(item[key]) : ""; }
function splitLines(value: string): string[] { return value.split("\n").map(item => item.trim()).filter(Boolean); }

function StageRail({current}: {current: string}) {
  const stages = ["project_understanding", "literature", "hypothesis", "experiment_planning", "experiment", "analysis", "research_review", "report_writing", "completed"];
  const currentIndex = Math.max(0, stages.indexOf(current));
  return <div className="stage-rail" aria-label="科研流程进度">{stages.map((stage, index) => <div key={stage} className={index < currentIndex ? "done" : index === currentIndex ? "current" : "future"}><span>{index < currentIndex ? "✓" : String(index + 1).padStart(2, "0")}</span><small>{titleCase(stage)}</small></div>)}</div>;
}

function OverviewPanel({project, snapshot}: {project: ProjectDetail; snapshot: ProjectSnapshot}) {
  const activeRuns = snapshot.runs.filter(item => ["queued", "running", "paused"].includes(String(item.run.status)));
  return <div className="dashboard-grid">
    <Section title="当前研究状态" eyebrow="研究流程" className="hero-panel">
      <div className="hero-state"><div><span className="eyebrow">当前阶段</span><h2>{titleCase(snapshot.state.stage)}</h2><p>{project.project.project_type === "topic_based" ? project.project.topic : project.project.source_root}</p></div><Badge value={snapshot.state.status} /></div>
      <StageRail current={snapshot.state.stage} />
      <div className="metric-grid"><Metric label="研究结论" value={snapshot.state.outcome ? titleCase(snapshot.state.outcome) : "尚未判定"} /><Metric label="正在运行的实验" value={activeRuns.length} /></div>
    </Section>
    <Section title="研究进展" eyebrow="研究记录" className="hero-panel"><div className="metric-grid"><Metric label="文献来源" value={snapshot.literature.sources.length} /><Metric label="证据条目" value={snapshot.literature.evidence.length} /><Metric label="实验运行" value={snapshot.runs.length} /><Metric label="分析结果" value={snapshot.analyses.length} /><Metric label="科研评审" value={snapshot.researchReviews.length} /><Metric label="论文产物" value={snapshot.papers.length} /></div></Section>
  </div>;
}

function UnderstandingPanel({project, snapshot, run}: {project: ProjectDetail; snapshot: ProjectSnapshot; run: ActionRunner}) {
  const bundle = snapshot.understanding;
  const context = record(bundle?.context);
  const userConstraints = record(context.user_constraints);
  const currentObjectives = list(userConstraints.research_objectives).map(value => text(value));
  const [objective, setObjective] = useState("");
  const completedImport = [...snapshot.imports].reverse().find(item => item.status === "completed");
  const summary = project.project.project_type === "topic_based" ? text(project.project.topic, text(context.summary)) : text(context.summary);
  const researchQuestions = list(context.research_questions).map(value => text(value)).filter(question => question !== summary && !currentObjectives.includes(question));
  const additionalRequirements = list(userConstraints.additional_constraints).map(value => text(value));

  useEffect(() => {
    setObjective(currentObjectives.join("\n") || text(project.project.topic));
  }, [context.context_id, project.project.topic]);

  async function understand() {
    await run("项目理解", () => api.understand(project.project.project_id, {
      constraints: {...userConstraints, research_objectives: splitLines(objective)},
      import_id: project.project.project_type === "existing_project" ? context.import_id ?? completedImport?.import_id ?? null : null
    }));
  }

  const correctionForm = <div className="stack-form"><FormField label="新的研究目标" hint="说明希望回答的问题；建议使用英文。"><textarea rows={5} value={objective} onChange={event => setObjective(event.target.value)} placeholder="输入修正后的研究目标……" /></FormField><button type="button" className="button-primary" disabled={!objective.trim()} onClick={understand}>保存并重新理解</button></div>;

  return <div className="main-column full-column">
      <Section title="系统理解结果" eyebrow={project.project.project_type === "topic_based" ? "Topic 研究" : "已有项目研究"}>
        {bundle ? <><div className="context-summary"><div><span>模式</span><Badge value={context.mode} /></div><div><span>验证状态</span><Badge value={context.verification_status} /></div></div><span className="eyebrow">研究目标</span><h3>{currentObjectives.join("；") || summary}</h3>{project.project.project_type === "existing_project" && <p className="lead-copy">{summary}</p>}{additionalRequirements.length > 0 && <p>补充要求：{additionalRequirements.join("；")}</p>}{researchQuestions.length > 0 && <div className="chip-list">{researchQuestions.map((question, index) => <span key={index}>{question}</span>)}</div>}</> : <Empty>尚未生成项目理解，请先确认研究目标。</Empty>}
        {bundle ? <details className="advanced-settings"><summary>修正研究目标</summary>{correctionForm}</details> : correctionForm}
      </Section>

      {project.project.project_type === "existing_project" && <Section title="Legacy Reuse Assessment" eyebrow="B mode boundary" action={snapshot.reuseAssessment && <Badge value={snapshot.reuseAssessment.approval_status} />}>
        {snapshot.reuseAssessment ? <><div className="metric-row"><Metric label="建议策略" value={titleCase(snapshot.reuseAssessment.recommended_strategy)} /><Metric label="复用项" value={records(snapshot.reuseAssessment.reuse_items).length} /><Metric label="风险" value={records(snapshot.reuseAssessment.risks).length} /></div><p className="lead-copy">{text(snapshot.reuseAssessment.approval_summary)}</p><RecordList items={records(snapshot.reuseAssessment.reuse_items)} render={(item, index) => <article className="record-card" key={index}><strong>{text(item.relative_path ?? item.kind)}</strong><p>{text(item.rationale ?? item.summary)}</p></article>} /></> : <Empty>完成 B 模式项目理解后生成复用评估。</Empty>}
      </Section>}

  </div>;
}

function LiteraturePanel({projectId, snapshot, run}: {projectId: string; snapshot: ProjectSnapshot; run: ActionRunner}) {
  const [network, setNetwork] = useState<"inherit" | "allow" | "deny">("inherit");
  const [showAllSources, setShowAllSources] = useState(false);
  const [showAllEvidence, setShowAllEvidence] = useState(false);
  const [showAllGaps, setShowAllGaps] = useState(false);
  const visibleSources = showAllSources ? snapshot.literature.sources : snapshot.literature.sources.slice(0, 5);
  const roleLabels: Record<string, string> = {background: "背景", method: "方法", contrast: "对照", core_support: "核心支持"};
  const evidencePriority: Record<string, number> = {core_support: 0, contrast: 1, method: 2, background: 3};
  const prioritizedEvidence = [...snapshot.literature.evidence].sort((left, right) => (evidencePriority[String(left.role)] ?? 4) - (evidencePriority[String(right.role)] ?? 4));
  const visibleEvidence = showAllEvidence ? prioritizedEvidence : prioritizedEvidence.slice(0, 5);
  const visibleGaps = showAllGaps ? snapshot.literature.gaps : snapshot.literature.gaps.slice(0, 5);
  const accessLabels: Record<string, string> = {metadata_only: "仅元数据", abstract_only: "仅摘要", full_text: "全文", imported_pdf: "导入 PDF"};
  return <div className="two-column-layout">
    <div className="main-column">
      <Section title="文献检索" eyebrow="检索与证据整理" action={<div className="button-row"><select value={network} onChange={event => setNetwork(event.target.value as typeof network)} aria-label="文献网络策略"><option value="inherit">继承项目网络策略</option><option value="allow">本次允许网络</option><option value="deny">本次禁止网络</option></select><button type="button" className="button-primary" onClick={() => run("文献检索", () => api.runLiterature(projectId, network === "inherit" ? null : network === "allow"))}>运行文献检索</button></div>}>
        {snapshot.literature.matrix ? <div className="metric-grid"><Metric label="文献来源" value={snapshot.literature.sources.length} /><Metric label="证据条目" value={snapshot.literature.evidence.length} /><Metric label="研究缺口" value={snapshot.literature.gaps.length} /></div> : <Empty>运行后将生成文献来源、证据和研究缺口。</Empty>}
      </Section>
      <Section title="文献来源" eyebrow={`共 ${snapshot.literature.sources.length} 篇`} action={snapshot.literature.sources.length > 5 && <button type="button" className="button-quiet" aria-expanded={showAllSources} onClick={() => setShowAllSources(value => !value)}>{showAllSources ? "收起" : `查看全部（${snapshot.literature.sources.length}）`}</button>}>
        <RecordList items={visibleSources} empty="尚未检索到文献来源。" render={(source, index) => <article className="record-card" key={String(source.source_id ?? index)}><div className="record-card-top"><strong>{text(source.title)}</strong></div><p>{list(source.authors).map(value => text(value)).join(", ") || "作者未知"} · {text(source.publication_year, "年份未知")}</p><div className="chip-list"><Badge value={accessLabels[String(source.access_level)] ?? text(source.access_level)} /><Badge value={source.existence_verified ? "来源已确认" : "来源待确认"} /><Badge value={source.metadata_verified ? "信息已核对" : "信息待核对"} /></div>{typeof source.landing_url === "string" && <a href={source.landing_url} target="_blank" rel="noreferrer" className="text-link">打开文献页面 ↗</a>}</article>} />
      </Section>
      <Section title="证据矩阵" eyebrow="优先展示核心支持与对照证据" action={snapshot.literature.evidence.length > 5 && <button type="button" className="button-quiet" aria-expanded={showAllEvidence} onClick={() => setShowAllEvidence(value => !value)}>{showAllEvidence ? "收起" : `查看全部证据（${snapshot.literature.evidence.length}）`}</button>}>
        <RecordList items={visibleEvidence} empty="尚未形成文献证据。" render={(evidence, index) => {
          const source = snapshot.literature.sources.find(item => item.source_id === evidence.source_id);
          const locator = record(evidence.locator);
          const location = [["版本", locator.version], ["页码", locator.pages], ["章节", locator.section], ["段落", locator.paragraph], ["图", locator.figure], ["表", locator.table], ["位置", locator.locator_text]].filter(([, value]) => Boolean(value)).map(([label, value]) => `${label}：${text(value)}`).join(" · ");
          return <article className="record-card" key={String(evidence.evidence_id ?? index)}><div className="record-card-top"><strong>{text(evidence.claim)}</strong><Badge value={roleLabels[String(evidence.role)] ?? text(evidence.role)} /></div><p>{text(evidence.support_summary)}</p><small>来源：{text(source?.title, "未匹配到文献来源")}</small><p>{location ? `定位：${location}` : "定位：暂无精确位置"}</p></article>;
        }} />
      </Section>
    </div>
    <aside className="side-column"><Section title="研究缺口" eyebrow="重点待回答问题" action={snapshot.literature.gaps.length > 5 && <button type="button" className="button-quiet" aria-expanded={showAllGaps} onClick={() => setShowAllGaps(value => !value)}>{showAllGaps ? "收起" : `查看全部缺口（${snapshot.literature.gaps.length}）`}</button>}><RecordList items={visibleGaps} empty="当前没有待补充的研究缺口。" render={(gap, index) => <article className="record-card" key={String(gap.gap_id ?? index)}><strong>{text(gap.statement ?? gap.description)}</strong><p>{text(gap.rationale ?? gap.why_it_matters ?? gap.missing_evidence)}</p>{Boolean(gap.uncertainty) && <small>不确定性：{text(gap.uncertainty)}</small>}</article>} /></Section></aside>
  </div>;
}

function PlanningPanel({projectId, snapshot, run}: {projectId: string; snapshot: ProjectSnapshot; run: ActionRunner}) {
  const hypothesis = latest(snapshot.hypotheses);
  const latestPlan = latest(snapshot.plans);
  const plan = latestPlan?.hypothesis_revision_id === hypothesis?.hypothesis_revision_id ? latestPlan : null;
  const candidates = records(hypothesis?.candidates);
  const [candidateId, setCandidateId] = useState("");
  const [feedback, setFeedback] = useState("我已核对该版本的证据、风险和可证伪性。");
  useEffect(() => { if (hypothesis) setCandidateId(String(hypothesis.recommended_candidate_id ?? candidates[0]?.candidate_id ?? "")); }, [hypothesis?.hypothesis_revision_id]);
  const hypothesisDecision = snapshot.planningApprovals.find(item => item.artifact_kind === "hypothesis" && item.artifact_id === hypothesis?.hypothesis_revision_id);
  const hypothesisApproved = hypothesisDecision?.decision === "approved" ? hypothesisDecision : undefined;
  const planApproval = snapshot.planningApprovals.find(item => item.artifact_kind === "experiment_plan" && item.artifact_id === plan?.plan_revision_id);
  const planApproved = planApproval?.decision === "approved";
  const recommendedCandidate = candidates.find(item => item.candidate_id === hypothesis?.recommended_candidate_id) ?? candidates[0];
  const otherCandidates = candidates.filter(item => item.candidate_id !== recommendedCandidate?.candidate_id);
  const selectedCandidate = candidates.find(item => item.candidate_id === (hypothesisApproved?.selected_candidate_id ?? hypothesis?.recommended_candidate_id)) ?? candidates[0];
  const generatedResearchQuestion = typeof hypothesis?.research_question === "string" ? hypothesis.research_question.trim() : "";
  const researchQuestion = generatedResearchQuestion || text(recommendedCandidate?.statement, "尚未形成明确的研究问题。");
  const planDraft = record(plan?.plan);
  const study = record(planDraft.study);
  const conditions = records(study.conditions);
  const controls = list(study.control_strategy).map(value => text(value));
  const primaryMetrics = records(planDraft.metrics).filter(metric => metric.primary === true);
  const budget = record(planDraft.budget);
  const activeArtifactId = plan?.plan_revision_id ?? hypothesis?.hypothesis_revision_id;
  const currentReview = [...snapshot.planningReviews].reverse().find(review => review.artifact_id === activeArtifactId);
  const majorDefects = records(currentReview?.defects).filter(defect => ["blocking", "major"].includes(String(defect.severity).toLowerCase()));

  const candidateChoice = (candidate: ApiRecord, recommended = false) => <label className={`candidate-card ${candidateId === candidate.candidate_id ? "selected" : ""}`} key={String(candidate.candidate_id)}>
    <input type="radio" name="candidate" value={String(candidate.candidate_id)} checked={candidateId === candidate.candidate_id} onChange={() => setCandidateId(String(candidate.candidate_id))} />
    <span className="candidate-radio" />
    {recommended && <span className="eyebrow">LLM 推荐</span>}
    <strong>{text(candidate.title)}</strong>
    <p>{text(candidate.statement)}</p>
    <small>为什么这样预测</small><p>{text(candidate.rationale)}</p>
    <small>什么结果会推翻它</small><p>{text(candidate.falsification_criterion)}</p>
  </label>;

  return <div className="main-column full-column">
    <Section title="研究问题" eyebrow="这项研究要回答什么">
      {hypothesis ? <article className="record-card"><p className="lead-copy">{researchQuestion}</p>{!generatedResearchQuestion && <InlineNotice tone="info">旧记录未保存独立研究问句，当前展示本研究要检验的内容；下次修订时会生成正式研究问题。</InlineNotice>}</article> : <Empty>先完成文献证据整理，再生成研究问题和预计答案。</Empty>}
    </Section>

    <Section title="预计答案" eyebrow="对研究问题的可证伪回答">
      {hypothesis ? hypothesisApproved && selectedCandidate ? <article className="record-card"><div className="record-card-top"><strong>{text(selectedCandidate.title)}</strong><Badge value="已选定" tone="good" /></div><p className="lead-copy">{text(selectedCandidate.statement)}</p><small>为什么这样预测</small><p>{text(selectedCandidate.rationale)}</p><small>什么结果会推翻它</small><p>{text(selectedCandidate.falsification_criterion)}</p></article> : <>
        <div className="candidate-grid">{recommendedCandidate && candidateChoice(recommendedCandidate, true)}</div>
        {otherCandidates.length > 0 && <details className="advanced-settings"><summary>查看其他预计答案（{otherCandidates.length}）</summary><div className="candidate-grid">{otherCandidates.map(candidate => candidateChoice(candidate))}</div></details>}
      </> : <Empty>生成研究设计后，这里会先展示 LLM 推荐答案，并允许切换其他候选。</Empty>}
    </Section>

    <Section title="实验计划" eyebrow="如何验证预计答案">
      {plan ? <>
        <h3>{text(study.name)}</h3><p className="lead-copy clamped-copy">{text(study.objective)}</p>
        <div className="candidate-grid">{conditions.map((condition, index) => <article className="record-card" key={String(condition.condition_id ?? index)}><div className="record-card-top"><strong>{text(condition.name)}</strong>{Boolean(condition.is_baseline) && <Badge value="baseline" />}</div><p>{text(condition.purpose)}</p></article>)}</div>
        {controls[0] && <InlineNotice><strong>对照策略：</strong>{controls[0]}</InlineNotice>}
        <span className="eyebrow">主要指标</span><div className="candidate-grid">{primaryMetrics.map((metric, index) => <article className="record-card" key={String(metric.metric_id ?? index)}><strong>{text(metric.name)}</strong><p className="clamped-copy">{text(metric.definition)}</p></article>)}</div>
        <div className="metric-grid"><Metric label="最大运行" value={text(budget.max_total_runs)} /><Metric label="计算预算" value={`${text(budget.max_total_compute_minutes)} 分钟 · ${text(budget.max_gpu_hours)} GPU 小时`} /></div>
        {Boolean(planDraft.b_mode_binding) && <InlineNotice tone="warn">该计划包含已有项目的代码复用、补充实验和结果复核安排。</InlineNotice>}
      </> : <Empty>{hypothesisApproved ? "研究方向已批准，可在下方生成实验计划。" : "批准研究问题和预计答案后，才能生成实验计划。"}</Empty>}
    </Section>

    <Section title="当前审批" eyebrow="确认研究方向与实验安排">
      {majorDefects.length > 0 && <><InlineNotice tone="warn">当前内容还有需要处理的重要问题：</InlineNotice><RecordList items={majorDefects} render={(defect, index) => <article className="record-card" key={index}><div className="record-card-top"><strong>{text(defect.summary)}</strong><Badge value={defect.severity} /></div><p>{text(defect.suggested_action)}</p></article>} /></>}
      {!hypothesis && <><InlineNotice>尚未生成研究设计。</InlineNotice><button type="button" className="button-primary full-button" onClick={() => run("生成研究设计", () => api.generateHypotheses(projectId, null, []))}>生成研究问题和预计答案</button></>}
      {hypothesis && !hypothesisApproved && <>
        <InlineNotice tone={hypothesisDecision?.decision === "rejected" ? "bad" : "warn"}>{hypothesisDecision?.decision === "rejected" ? "研究方向已退回，请根据反馈生成修订内容。" : "请确认研究问题和所选预计答案是否构成正确的研究方向。"}</InlineNotice>
        <FormField label="审批或修改意见" wide><textarea rows={3} value={feedback} onChange={event => setFeedback(event.target.value)} /></FormField>
        <div className="button-row">
          <button type="button" disabled={!feedback.trim()} onClick={() => run("修订研究设计", () => api.generateHypotheses(projectId, id(hypothesis, "hypothesis_revision_id") || null, [feedback]))}>根据意见重新生成</button>
          {hypothesisDecision?.decision !== "rejected" && <><button type="button" className="button-primary" disabled={!candidateId || !feedback.trim()} onClick={() => run("批准研究方向", () => api.decideHypothesis(projectId, String(hypothesis.hypothesis_revision_id), {decision: "approved", feedback, actor_id: "local_user", selected_candidate_id: candidateId}))}>批准研究问题与预计答案</button><button type="button" className="button-danger" disabled={!feedback.trim()} onClick={() => run("退回研究方向", () => api.decideHypothesis(projectId, String(hypothesis.hypothesis_revision_id), {decision: "rejected", feedback, actor_id: "local_user", selected_candidate_id: null}))}>退回修改</button></>}
        </div>
      </>}
      {hypothesisApproved && !plan && <><InlineNotice tone="good">研究问题和预计答案已批准。</InlineNotice><button type="button" className="button-primary full-button" onClick={() => run("生成实验计划", () => api.generatePlan(projectId, String(hypothesis?.hypothesis_revision_id), null, []))}>生成实验计划</button></>}
      {plan && !planApproved && <>
        <InlineNotice tone={planApproval?.decision === "rejected" ? "bad" : "warn"}>{planApproval?.decision === "rejected" ? "实验计划已退回，请根据反馈生成修订计划。" : "请确认实验条件、对照、主要指标和预算是否可执行。"}</InlineNotice>
        <FormField label="审批或修改意见" wide><textarea rows={3} value={feedback} onChange={event => setFeedback(event.target.value)} /></FormField>
        <div className="button-row">
          {planApproval?.decision === "rejected" ? <button type="button" className="button-primary" disabled={!feedback.trim()} onClick={() => run("修订实验计划", () => api.generatePlan(projectId, String(hypothesis?.hypothesis_revision_id), id(plan, "plan_revision_id") || null, [feedback]))}>根据意见生成修订计划</button> : <><button type="button" className="button-primary" disabled={!feedback.trim()} onClick={() => run("批准实验计划", () => api.decidePlan(projectId, String(plan.plan_revision_id), {decision: "approved", feedback, actor_id: "local_user", selected_candidate_id: null}))}>批准实验计划</button><button type="button" className="button-danger" disabled={!feedback.trim()} onClick={() => run("退回实验计划", () => api.decidePlan(projectId, String(plan.plan_revision_id), {decision: "rejected", feedback, actor_id: "local_user", selected_candidate_id: null}))}>退回修改</button></>}
        </div>
      </>}
      {plan && planApproved && <>
        <InlineNotice tone={snapshot.formalGate?.allowed ? "good" : "warn"}>{snapshot.formalGate?.allowed ? "研究设计已全部批准，可以进入正式实验。" : `实验计划已批准，但暂不能进入正式实验：${list(snapshot.formalGate?.reasons).map(value => text(value)).join("；") || "仍有必要条件未满足"}`}</InlineNotice>
        <details className="advanced-settings"><summary>需要修改研究方向或实验计划</summary><div className="form-grid"><FormField label="修改意见" wide><textarea rows={3} value={feedback} onChange={event => setFeedback(event.target.value)} /></FormField><div className="button-row field-wide"><button type="button" disabled={!feedback.trim()} onClick={() => run("修订研究设计", () => api.generateHypotheses(projectId, id(hypothesis, "hypothesis_revision_id") || null, [feedback]))}>修改研究问题或预计答案</button><button type="button" disabled={!feedback.trim()} onClick={() => run("修订实验计划", () => api.generatePlan(projectId, String(hypothesis?.hypothesis_revision_id), id(plan, "plan_revision_id") || null, [feedback]))}>修改实验计划</button></div></div></details>
      </>}
    </Section>
  </div>;
}

function ArtifactGallery({projectId, artifacts, kind}: {projectId: string; artifacts: ApiRecord[]; kind: "experiment" | "analysis"}) {
  return <div className="artifact-grid">{artifacts.map((artifact, index) => {
    const artifactId = String(artifact.artifact_id);
    const url = kind === "experiment" ? artifactUrl.experiment(projectId, artifactId) : artifactUrl.analysis(projectId, artifactId);
    const isImage = String(artifact.media_type).startsWith("image/") || artifact.kind === "figure";
    return <article key={artifactId || index} className="artifact-card">{isImage && <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={text(artifact.relative_path, "研究图片")} /></a>}<div><Badge value={artifact.kind} /><strong>{text(artifact.relative_path)}</strong><code>{shortId(artifact.sha256)}</code><a href={url} target="_blank" rel="noreferrer" className="text-link">预览 / 下载 ↗</a></div></article>;
  })}</div>;
}

function ExperimentsPanel({project, snapshot, run}: {project: ProjectDetail; snapshot: ProjectSnapshot; run: ActionRunner}) {
  const projectId = project.project.project_id;
  const plan = latest(snapshot.plans);
  const planDraft = record(plan?.plan);
  const runSpecs = records(planDraft.runs);
  const [profileId, setProfileId] = useState("");
  const [profileFeedback, setProfileFeedback] = useState("沿用该视觉规范生成新的、证据可追溯的图片。");
  const [figureTitle, setFigureTitle] = useState("");
  const [figurePurpose, setFigurePurpose] = useState("");
  const [figureMetrics, setFigureMetrics] = useState("");
  const profiles = snapshot.visualizationProfiles;
  const approvedProfiles = profiles.filter(item => item.approval_status === "approved");
  const legacyFigures = records(record(snapshot.understanding?.context).materials).filter(item => list(item.kinds).includes("figure"));
  const context = record(snapshot.understanding?.context);
  const contextId = id(context, "context_id");
  const importId = typeof context.import_id === "string" ? context.import_id : "";

  async function createFigureSpec() {
    const profile = approvedProfiles[0] ?? profiles[0];
    await run("FigureSpec", () => api.createFigureSpec(projectId, {
      context_id: contextId, title: figureTitle, purpose: figurePurpose,
      visualization_profile_id: profile?.profile_id ?? null,
      panels: [{panel_id: "panel_a", purpose: figurePurpose, metrics: splitLines(figureMetrics), input_artifact_ids: []}],
      legacy_reference_paths: [], caption: figurePurpose, supplementary_requirements: [], output_formats: ["pdf", "png"]
    }));
    setFigureTitle(""); setFigurePurpose(""); setFigureMetrics("");
  }

  return <div className="main-column full-column">
    {project.project.project_type === "existing_project" && profiles.length > 0 && <Section title="VisualizationProfile" eyebrow="Inherited visual language">
      <RecordList items={profiles} render={(profile, index) => <RecordCard key={index} item={profile} idKeys={["profile_id"]} titleKeys={["caption_style", "profile_id"]}><div className="swatch-row">{list(profile.colors).map((color, colorIndex) => <span key={colorIndex} style={{backgroundColor: text(color)}} title={text(color)} />)}</div><p>{list(profile.layouts).map(value => text(value)).join(" · ") || "未检测到布局"}</p>{profile.approval_status === "pending" && <><textarea value={profileFeedback} onChange={event => setProfileFeedback(event.target.value)} rows={2} /><div className="button-row"><button type="button" className="button-primary" onClick={() => run("批准视觉规范", () => api.decideProfile(projectId, String(profile.profile_id), true, profileFeedback))}>批准</button><button type="button" className="button-danger" onClick={() => run("拒绝视觉规范", () => api.decideProfile(projectId, String(profile.profile_id), false, profileFeedback))}>拒绝</button></div></>}</RecordCard>} />
    </Section>}

    <Section title="Study implementation" eyebrow="Modeling Scientist + Research Engineer" action={<div className="button-row">{approvedProfiles.length > 0 && <select value={profileId} onChange={event => setProfileId(event.target.value)} aria-label="可视化规范"><option value="">不指定视觉规范</option>{approvedProfiles.map(profile => <option value={String(profile.profile_id)} key={String(profile.profile_id)}>{shortId(profile.profile_id)}</option>)}</select>}<button type="button" className="button-primary" disabled={!plan} onClick={() => run("创建 Study", () => api.createStudy(projectId, {plan_revision_id: plan?.plan_revision_id, visualization_profile_id: profileId || null, parent_implementation_id: latest(snapshot.implementations)?.implementation_revision_id ?? null}))}>实现已批准 Plan</button></div>}>
      <RecordList items={snapshot.studies} render={(study, index) => <RecordCard key={index} item={study} idKeys={["study_id"]} titleKeys={["name"]}><p>{text(study.objective)}</p><div className="chip-list"><Badge value={study.status} />{Boolean(study.visualization_profile_id) && <Badge value="visual profile bound" />}</div><div className="run-spec-actions">{runSpecs.map((spec, specIndex) => <div key={String(spec.run_spec_id ?? specIndex)}><span><code>{shortId(spec.run_spec_id)}</code><small>{text(record(records(record(planDraft.study).conditions).find(item => item.condition_id === spec.condition_id)).name, text(spec.condition_id))}</small></span><button type="button" onClick={() => run("Smoke run", () => api.createRun(projectId, String(study.study_id), String(spec.run_spec_id), true))}>Smoke</button><button type="button" className="button-primary" onClick={() => run("Formal run", () => api.createRun(projectId, String(study.study_id), String(spec.run_spec_id), false))}>Formal</button></div>)}</div><button type="button" className="button-primary" onClick={() => run("分析与实验审核", () => api.createAnalysis(projectId, String(study.study_id)))}>运行确定性分析与审核</button></RecordCard>} />
    </Section>

    {(snapshot.lineage.length > 0 || snapshot.implementationDiffs.length > 0) && <Section title="Code Lineage 与实现 Diff" eyebrow="Source → derived workspace">
      {snapshot.lineage.length > 0 && <RecordList items={snapshot.lineage} render={(item, index) => <RecordCard key={index} item={item} idKeys={["lineage_id"]} titleKeys={["derived_workspace_path"]}><p><code>{text(item.source_relative_path)}</code> → <code>{text(item.derived_workspace_path)}</code></p><div className="chip-list"><Badge value={item.strategy} /><Badge value={item.verification} /><Badge value={item.plan_approval_status} /></div></RecordCard>} />}
      {snapshot.implementationDiffs.map((diff, index) => <details className="diff-block" key={String(diff.implementation_revision_id ?? index)}><summary>Implementation {shortId(diff.implementation_revision_id)} · {records(diff.entries).length} files</summary>{records(diff.entries).map((entry, entryIndex) => <article key={entryIndex}><div><strong>{text(entry.derived_relative_path)}</strong><Badge value={entry.strategy} /></div><pre>{text(entry.unified_diff, "文件内容未发生文本变化")}</pre></article>)}</details>)}
    </Section>}

    {((plan && contextId) || snapshot.figureSpecs.length > 0) && <Section title="FigureSpec" eyebrow="Planned figures">
      {plan && contextId && <div className="form-grid"><FormField label="图标题"><input value={figureTitle} onChange={event => setFigureTitle(event.target.value)} /></FormField><FormField label="指标（每行一项）"><textarea rows={3} value={figureMetrics} onChange={event => setFigureMetrics(event.target.value)} /></FormField><FormField label="科研目的" wide><textarea rows={3} value={figurePurpose} onChange={event => setFigurePurpose(event.target.value)} /></FormField><button type="button" className="button-primary field-wide" disabled={!figureTitle || !figurePurpose} onClick={createFigureSpec}>创建 FigureSpec</button></div>}
      {snapshot.figureSpecs.length > 0 && <RecordList items={snapshot.figureSpecs} render={(spec, index) => <RecordCard key={index} item={spec} idKeys={["figure_spec_id"]} titleKeys={["title"]}><p>{text(spec.purpose)}</p></RecordCard>} />}
    </Section>}

    <Section title="Run、日志、指标与 Artifact" eyebrow="Pause · resume · cancel · immutable attempts">
      <RecordList items={snapshot.runs.map(item => ({...item.run, _view: item} as ApiRecord))} render={(item, index) => {
        const view = item._view as unknown as ProjectSnapshot["runs"][number];
        const status = String(item.status);
        return <RecordCard key={index} item={item} idKeys={["run_id"]} titleKeys={["run_spec_id"]}><div className="metric-row"><Metric label="Attempt" value={text(item.attempt)} /><Metric label="Smoke" value={item.smoke ? "yes" : "no"} /><Metric label="Evidence eligible" value={item.evidence_eligible ? "yes" : "no"} /><Metric label="Wall time" value={`${numeric(record(item.resource_usage).wall_seconds).toFixed(2)}s`} /></div><div className="button-row">{["queued", "running"].includes(status) && <button type="button" onClick={() => run("暂停 Run", () => api.controlRun(projectId, String(item.run_id), "pause"))}>暂停</button>}{["paused", "stale", "failed"].includes(status) && <button type="button" className="button-primary" onClick={() => run("恢复 Run", () => api.controlRun(projectId, String(item.run_id), "resume"))}>恢复为新 attempt</button>}{["queued", "running", "paused"].includes(status) && <button type="button" className="button-danger" onClick={() => run("取消 Run", () => api.controlRun(projectId, String(item.run_id), "cancel"))}>取消</button>}</div>{view.logs && <details className="log-view" open={status === "failed"}><summary>运行日志{view.logs.truncated ? "（尾部，已截断）" : ""}</summary><div><strong>stdout</strong><pre>{view.logs.stdout || "（无输出）"}</pre><strong>stderr</strong><pre>{view.logs.stderr || "（无输出）"}</pre></div></details>}<ArtifactGallery projectId={projectId} artifacts={view.artifacts} kind="experiment" /></RecordCard>;
      }} />
    </Section>

    <Section title="分析结果与可视化" eyebrow="Deterministic statistics">
      {project.project.project_type === "existing_project" && (legacyFigures.length || snapshot.analyses.some(item => item.artifacts.some(artifact => artifact.kind === "figure"))) && <div className="figure-compare"><div><span className="eyebrow">Legacy / unverified</span>{legacyFigures.map((figure, index) => <article key={index}>{importId && <img src={artifactUrl.imported(projectId, importId, String(figure.relative_path))} alt={`Legacy unverified: ${text(figure.relative_path)}`} />}<Badge value="legacy unverified" /><small>{text(figure.relative_path)}</small></article>)}</div><div><span className="eyebrow">New / artifact-bound</span>{snapshot.analyses.flatMap(item => item.artifacts.filter(artifact => artifact.kind === "figure")).map((figure, index) => <article key={index}><img src={artifactUrl.analysis(projectId, String(figure.artifact_id))} alt={text(figure.relative_path)} /><Badge value="new verified figure" /><small>{text(figure.relative_path)}</small></article>)}</div></div>}
      {snapshot.analyses.map((analysisView, index) => <article className="analysis-card" key={String(analysisView.analysis.analysis_id ?? index)}><div className="record-card-top"><div><strong>Analysis {shortId(analysisView.analysis.analysis_id)}</strong><code>{shortId(analysisView.analysis.content_hash)}</code></div><Badge value={analysisView.analysis.outcome} /></div><AuditJson value={analysisView.analysis} label="查看统计结果与比较" /><ArtifactGallery projectId={projectId} artifacts={analysisView.artifacts} kind="analysis" /></article>)}
      {!snapshot.analyses.length && <Empty>完成所有正式运行后生成分析、CSV、JSON 和 SVG。</Empty>}
    </Section>
  </div>;
}

function ReviewPanel({projectId, snapshot, run}: {projectId: string; snapshot: ProjectSnapshot; run: ActionRunner}) {
  return <div className="two-column-layout"><div className="main-column">
    <Section title="Verification 与 Scientific Review" eyebrow="Fresh deterministic checks">
      {snapshot.analyses.map((view, index) => { const analysisId = String(view.analysis.analysis_id); const verification = latest(view.verifications); const scientific = latest(view.scientificReviews); return <article className="review-stage-card" key={analysisId || index}><div className="record-card-top"><div><strong>Analysis {shortId(analysisId)}</strong><Badge value={view.analysis.outcome} /></div><div className="button-row"><button type="button" onClick={() => run("重新验证 Analysis", () => api.verifyAnalysis(projectId, analysisId))}>独立验证</button><button type="button" className="button-primary" disabled={!verification} onClick={() => run("Scientific Review", () => api.createScientificReview(projectId, analysisId, String(verification?.verification_id)))}>实验科研审核</button><button type="button" className="button-primary" disabled={!scientific} onClick={() => run("Research Review", () => api.createResearchReview(projectId, analysisId, String(scientific?.review_id)))}>正式 Research Review</button></div></div><div className="metric-row"><Metric label="Verification" value={verification ? <Badge value={verification.passed ? "passed" : "failed"} /> : "—"} /><Metric label="Plan" value={verification ? (verification.plan_verified ? "verified" : "failed") : "—"} /><Metric label="Statistics" value={verification ? (verification.statistics_verified ? "verified" : "failed") : "—"} /><Metric label="Scientific policy" value={scientific ? titleCase(scientific.policy_recommendation) : "—"} /></div>{verification && <AuditJson value={verification} label="Verification findings" />}{scientific && <AuditJson value={scientific} label="Scientific Review" />}</article>; })}
      {!snapshot.analyses.length && <Empty>分析完成后可运行独立 Verification 和 Scientific Review。</Empty>}
    </Section>
    <Section title="Independent Research Review" eyebrow="Meta + 3 isolated specialists + policy guard">
      <RecordList items={snapshot.researchReviews} render={(reviewResult, index) => { const reviewRecord = record(reviewResult.record); const policy = record(reviewResult.policy_decision); const specialists = records(reviewResult.specialist_reviews); const transition = reviewResult.transition; return <RecordCard key={index} item={reviewRecord} idKeys={["review_run_id"]} titleKeys={["final_decision", "review_run_id"]}><div className="metric-row"><Metric label="Policy decision" value={<Badge value={policy.final_decision ?? reviewRecord.final_decision} />} /><Metric label="Specialists" value={specialists.length} /><Metric label="Claims" value={records(reviewResult.claims).length} /><Metric label="Applied" value={transition ? "yes" : "no"} /></div>{specialists.map((specialist, specialistIndex) => <AuditJson key={specialistIndex} value={specialist} label={`${titleCase(specialist.role)} report`} />)}<AuditJson value={policy} label="Deterministic Policy Guard" />{!transition && <button type="button" className="button-primary" onClick={() => run("应用 Research Review 决策", () => api.applyResearchReview(projectId, String(reviewRecord.review_run_id), snapshot.state.revision))}>应用精确评审决策</button>}</RecordCard>; }} />
    </Section>
  </div><aside className="side-column"><Section title="EvidenceClaims" eyebrow="Paper-ready claims">{snapshot.analyses.flatMap(item => item.evidenceClaims).length ? <RecordList items={snapshot.analyses.flatMap(item => item.evidenceClaims)} render={(claim, index) => <RecordCard key={index} item={claim} idKeys={["claim_id"]} titleKeys={["statement"]}><Badge value={claim.outcome} /><p>{records(claim.evidence).length} Artifact bindings</p></RecordCard>} /> : <Empty>Research Review 将主要结论绑定到 Artifact。</Empty>}</Section></aside></div>;
}

function PaperPanel({projectId, snapshot, run}: {projectId: string; snapshot: ProjectSnapshot; run: ActionRunner}) {
  const [target, setTarget] = useState("neurips");
  const lastReview = latest(snapshot.researchReviews);
  const reviewRecord = record(lastReview?.record);
  return <div className="main-column full-column">
    <Section title="Top-conference writing team" eyebrow="Five roles · evidence-bound" action={<div className="button-row"><select value={target} onChange={event => setTarget(event.target.value)} aria-label="目标会议"><option value="neurips">NeurIPS-style</option><option value="icml">ICML-style</option><option value="iclr">ICLR-style</option><option value="generic_top_conference">Generic top conference</option></select><button type="button" className="button-primary" disabled={!reviewRecord.review_run_id || !["report_planning", "report_writing", "report_review"].includes(snapshot.state.stage)} onClick={() => run("生成并评审论文", () => api.createPaper(projectId, String(reviewRecord.review_run_id), snapshot.state.revision, target))}>生成论文</button></div>}>
      <div className="role-strip">{["Lead Author", "Technical Editor", "Citation Editor", "Presentation Editor", "Top-Conference Reviewer"].map((role, index) => <div key={role}><span>0{index + 1}</span><strong>{role}</strong></div>)}</div>
      <InlineNotice>主要数字必须绑定 Artifact，主要结论必须绑定 EvidenceClaim，引用必须绑定真实 LiteratureSource 与定位；证据不足会自动降低结论。</InlineNotice>
    </Section>
    {snapshot.papers.map((paperResult, index) => {
      const paperRecord = record(paperResult.record);
      const revisions = records(paperResult.revisions);
      const reviews = records(paperResult.reviews);
      const artifacts = records(paperResult.artifacts);
      const paperId = String(paperRecord.paper_id ?? "");
      const pdf = artifacts.find(item => item.kind === "pdf");
      const preview = artifacts.find(item => item.kind === "markdown_preview");
      const tex = artifacts.find(item => item.kind === "paper_tex");
      const finalRevision = latest(revisions);
      const content = record(finalRevision?.content);
      const pdfUrl = pdf ? artifactUrl.paper(projectId, paperId, String(pdf.paper_artifact_id)) : "";
      return <article className="paper-workspace" key={paperId || index}>
        <div className="paper-heading"><div><span className="eyebrow">{titleCase(paperRecord.target)} · revision {text(finalRevision?.revision)}</span><h2>{text(content.title, "Untitled manuscript")}</h2><code>{shortId(paperRecord.content_hash)}</code></div><Badge value={paperRecord.status} /></div>
        <div className="paper-layout"><div className="paper-preview">{pdf ? <iframe title={`PDF ${text(content.title)}`} src={pdfUrl} /> : <Empty>PDF 尚未通过构建与视觉检查。</Empty>}</div><aside><div className="button-stack">{pdf && <a className="button-primary link-button" href={`${pdfUrl}?download=true`}>下载 PDF</a>}{preview && <a className="button-quiet link-button" href={artifactUrl.paper(projectId, paperId, String(preview.paper_artifact_id))} target="_blank" rel="noreferrer">Markdown preview</a>}{tex && <a className="button-quiet link-button" href={`${artifactUrl.paper(projectId, paperId, String(tex.paper_artifact_id))}?download=true`}>下载 paper.tex</a>}</div><h3>Outline</h3><ol className="outline-list">{records(content.sections).map((section, sectionIndex) => <li key={sectionIndex}>{text(section.title ?? section.section)}</li>)}</ol><h3>Reviewer defects</h3>{reviews.map((review, reviewIndex) => <div className="review-defects" key={reviewIndex}><div><Badge value={review.recommendation} /><span>Revision {text(review.revision)}</span></div>{records(review.defects).map((defect, defectIndex) => <p key={defectIndex}><Badge value={defect.severity} /> {text(defect.summary)}</p>)}</div>)}<AuditJson value={paperResult.quality_report} label="质量门禁" /></aside></div>
        <details className="artifact-manifest"><summary>{artifacts.length} 个论文 Artifact</summary><div className="record-list">{artifacts.map((artifact, artifactIndex) => <a key={artifactIndex} href={artifactUrl.paper(projectId, paperId, String(artifact.paper_artifact_id))} target="_blank" rel="noreferrer"><Badge value={artifact.kind} /><span>{text(artifact.relative_path)}</span><code>{shortId(artifact.sha256)}</code></a>)}</div></details>
      </article>;
    })}
    {!snapshot.papers.length && <Section title="论文产物" eyebrow="Awaiting reviewed evidence"><Empty>应用合格的 Research Review 决策后，可生成 LaTeX、BibTeX、图表、附录、Markdown 与 PDF。</Empty></Section>}
  </div>;
}

function ActivityPanel({snapshot}: {snapshot: ProjectSnapshot}) {
  const totals = snapshot.agentRuns.reduce<{input: number; output: number}>((sum, item) => ({input: sum.input + numeric(item.input_tokens), output: sum.output + numeric(item.output_tokens)}), {input: 0, output: 0});
  return <div className="two-column-layout"><div className="main-column"><Section title="Multi-Agent activity" eyebrow="Provider · model · tokens · immutable output"><div className="metric-row"><Metric label="Agent runs" value={snapshot.agentRuns.length} /><Metric label="Input tokens" value={totals.input.toLocaleString()} /><Metric label="Output tokens" value={totals.output.toLocaleString()} /><Metric label="Events" value={snapshot.events.length} /></div><RecordList items={snapshot.agentRuns.slice().reverse()} render={(agent, index) => <RecordCard key={index} item={agent} idKeys={["agent_run_id", "run_id"]} titleKeys={["role", "agent_kind"]}><div className="agent-meta"><span>{text(agent.provider_id ?? agent.provider)} / {text(agent.model)}</span><span>↑ {numeric(agent.input_tokens)} · ↓ {numeric(agent.output_tokens)}</span></div><p>{text(agent.operation)}</p></RecordCard>} /></Section></div><aside className="side-column"><Section title="Event journal" eyebrow="Refresh-safe cursor"><RecordList items={snapshot.events.slice().reverse()} render={(event, index) => <article className="timeline-row" key={String(event.cursor ?? index)}><span className="event-dot" /><div><strong>{text(event.summary)}</strong><small>#{text(event.cursor)} · {text(event.event_type)} · {dateTime(event.created_at)}</small></div></article>} /></Section><Section title="Durable jobs" eyebrow="Worker recovery"><RecordList items={snapshot.jobs.slice().reverse()} render={(job, index) => <RecordCard key={index} item={job} idKeys={["job_id"]} titleKeys={["kind"]}><p>{text(job.error, `${text(job.attempts, "0")} attempts`)}</p></RecordCard>} /></Section></aside></div>;
}

export function ProjectWorkbench({project, snapshot, runAction}: {project: ProjectDetail; snapshot: ProjectSnapshot; runAction: ActionRunner}) {
  const [tab, setTab] = useState<WorkbenchTab>(() => STAGE_TO_TAB[snapshot.state.stage] ?? "overview");
  useEffect(() => { setTab(STAGE_TO_TAB[snapshot.state.stage] ?? "overview"); }, [project.project.project_id]);
  const panel = useMemo(() => {
    const projectId = project.project.project_id;
    if (tab === "overview") return <OverviewPanel project={project} snapshot={snapshot} />;
    if (tab === "understanding") return <UnderstandingPanel project={project} snapshot={snapshot} run={runAction} />;
    if (tab === "literature") return <LiteraturePanel projectId={projectId} snapshot={snapshot} run={runAction} />;
    if (tab === "planning") return <PlanningPanel projectId={projectId} snapshot={snapshot} run={runAction} />;
    if (tab === "experiments") return <ExperimentsPanel project={project} snapshot={snapshot} run={runAction} />;
    if (tab === "review") return <ReviewPanel projectId={projectId} snapshot={snapshot} run={runAction} />;
    if (tab === "paper") return <PaperPanel projectId={projectId} snapshot={snapshot} run={runAction} />;
    return <ActivityPanel snapshot={snapshot} />;
  }, [tab, project, snapshot, runAction]);
  return <><nav className="workbench-tabs" aria-label="项目工作区">{TABS.map(item => <button key={item.id} type="button" className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}><span>{item.index}</span>{item.label}</button>)}</nav><main className="workbench">{panel}</main></>;
}
