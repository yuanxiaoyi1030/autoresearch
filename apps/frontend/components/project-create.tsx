// Purpose: Creates generic A-mode Topic or B-mode existing-project entries without fixed research domains.
"use client";

import {useState} from "react";
import type {FormEvent} from "react";

import {api} from "@/lib/api";
import type {ProjectDetail, ProjectType} from "@/lib/types";
import {FormField, InlineNotice, Segmented} from "./ui";

export function ProjectCreate({onCreated, onCancel}: {onCreated: (project: ProjectDetail) => Promise<void>; onCancel?: () => void}) {
  const [mode, setMode] = useState<ProjectType>("topic_based");
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [additionalRequirements, setAdditionalRequirements] = useState("");
  const [sourceRoot, setSourceRoot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const project = await api.createProject(mode === "topic_based"
        ? {title: title.trim(), project_type: mode, topic: objective.trim()}
        : {title: title.trim(), project_type: mode, source_root: sourceRoot.trim()});
      const imported = mode === "existing_project" ? await api.importProject(project.project.project_id, sourceRoot.trim()) : null;
      await api.understand(project.project.project_id, {
        constraints: {
          research_objectives: [objective.trim()], compute_budget: null, time_budget: null,
          network_allowed: false, allowed_dependencies: [], forbidden_dependencies: [],
          data_constraints: [], methodological_constraints: [], output_requirements: [],
          additional_constraints: additionalRequirements.trim() ? [additionalRequirements.trim()] : []
        },
        import_id: imported?.import_id ?? null
      });
      const reconciled = await api.reconcileWorkflow(project.project.project_id);
      project.state = reconciled.state as ProjectDetail["state"];
      await onCreated(project);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  }

  return <div className="create-layout">
    <div className="create-story">
      <span className="eyebrow">New research workspace</span>
      <h1>从问题或已有项目开始</h1>
      <p>每个项目拥有独立的导入快照、运行、证据、评审和论文历史。已有项目只读导入，原始代码不会被直接执行。</p>
      <div className="mode-explainer"><div><strong>A</strong><span>Topic 模式</span><p>从任意研究问题出发，搜索文献、提出假设并设计新实验。</p></div><div><strong>B</strong><span>已有项目</span><p>理解既有代码、实验与图形规范，在审批后的复用边界内补充研究。</p></div></div>
    </div>
    <form className="create-form" onSubmit={submit}>
      <Segmented value={mode} label="项目入口模式" options={[{value: "topic_based", label: "A · Topic"}, {value: "existing_project", label: "B · 已有项目"}]} onChange={setMode} />
      <FormField label="项目名称" wide><input value={title} onChange={event => setTitle(event.target.value)} placeholder="例如：鲁棒表征学习中的归纳偏置" required /></FormField>
      <FormField label="研究目标" hint="建议使用英文描述，以便后续更准确地检索国际文献。" wide><textarea rows={7} value={objective} onChange={event => setObjective(event.target.value)} placeholder="描述希望回答的问题、研究对象和需要验证的关系……" required /></FormField>
      {mode === "existing_project" && <FormField label="已有项目目录" hint="必须位于后端配置的 allowed_import_roots 内；导入时只读取并复制快照。" wide><input value={sourceRoot} onChange={event => setSourceRoot(event.target.value)} placeholder="D:\ml_project\your_project" required /></FormField>}
      <details className="advanced-settings"><summary>补充要求（可选）</summary><FormField label="补充要求" hint="例如计算限制、数据要求或希望生成的产物。" wide><textarea rows={4} value={additionalRequirements} onChange={event => setAdditionalRequirements(event.target.value)} placeholder="例如：仅使用 CPU；输出实验图表和英文论文。" /></FormField></details>
      {mode === "existing_project" && <InlineNotice tone="warn">导入不会运行源码、Notebook 或二进制文件；legacy 结果在复现前保持 unverified。</InlineNotice>}
      {error && <InlineNotice tone="bad">{error}</InlineNotice>}
      <div className="button-row"><button type="submit" className="button-primary" disabled={busy}>{busy ? "正在建立并理解…" : "建立研究项目"}</button>{onCancel && <button type="button" className="button-quiet" onClick={onCancel}>取消</button>}</div>
    </form>
  </div>;
}
