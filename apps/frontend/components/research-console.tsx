// Purpose: Restores the active project from backend persistence and coordinates the complete local UI.
"use client";

import {useCallback, useEffect, useMemo, useRef, useState} from "react";

import {api, loadProjectSnapshot} from "@/lib/api";
import {dateTime, text, titleCase} from "@/lib/format";
import type {LLMConfigView, ProjectDetail, ProjectSnapshot, RuntimeHealth} from "@/lib/types";
import {ProjectCreate} from "./project-create";
import {ProjectWorkbench} from "./project-workbench";
import {ProviderConsole} from "./provider-console";
import {Badge, InlineNotice} from "./ui";

type AppView = "project" | "create" | "settings";

export function ResearchConsole() {
  const [projects, setProjects] = useState<ProjectDetail[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<ProjectSnapshot | null>(null);
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [llm, setLLM] = useState<LLMConfigView | null>(null);
  const [view, setView] = useState<AppView>("project");
  const [loading, setLoading] = useState(true);
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [notice, setNotice] = useState<{tone: "good" | "bad" | "info"; message: string} | null>(null);
  const refreshLock = useRef(false);
  const latestCursor = useRef(0);

  const selected = useMemo(() => projects.find(item => item.project.project_id === selectedId) ?? null, [projects, selectedId]);

  const updateUrl = useCallback((projectId: string | null) => {
    const url = new URL(window.location.href);
    if (projectId) url.searchParams.set("project", projectId); else url.searchParams.delete("project");
    window.history.replaceState({}, "", url);
  }, []);

  const refreshSystem = useCallback(async () => {
    const [runtime, llmView] = await Promise.all([api.health(), api.getLLMConfig()]);
    setHealth(runtime); setLLM(llmView);
  }, []);

  const refreshProjects = useCallback(async (preferred?: string | null) => {
    const values = await api.listProjects();
    setProjects(values);
    const fromUrl = new URL(window.location.href).searchParams.get("project");
    const next = [preferred, fromUrl, selectedId, values[0]?.project.project_id].find(candidate => candidate && values.some(item => item.project.project_id === candidate)) ?? null;
    setSelectedId(next); updateUrl(next);
    if (!values.length) setView("create");
    return next;
  }, [selectedId, updateUrl]);

  const refreshSnapshot = useCallback(async (projectId = selectedId) => {
    if (!projectId || refreshLock.current) return;
    refreshLock.current = true;
    try {
      const value = await loadProjectSnapshot(projectId);
      latestCursor.current = Number(value.events.at(-1)?.cursor ?? 0);
      setSnapshot(value);
      setProjects(current => current.map(item => item.project.project_id === projectId ? {...item, state: value.state} : item));
    } finally { refreshLock.current = false; }
  }, [selectedId]);

  useEffect(() => {
    let active = true;
    Promise.all([refreshSystem(), refreshProjects()]).catch(error => {
      if (active) setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)});
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedId || view !== "project") { setSnapshot(null); return; }
    setLoading(true);
    refreshSnapshot(selectedId).catch(error => setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)})).finally(() => setLoading(false));
    const eventsTimer = window.setInterval(async () => {
      try {
        const events = await api.listEvents(selectedId, latestCursor.current, 100);
        if (events.length) await refreshSnapshot(selectedId);
      } catch (error) { setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)}); }
    }, 1800);
    const recoveryTimer = window.setInterval(() => {
      void refreshSnapshot(selectedId).catch(error => {
        setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)});
      });
    }, 8000);
    return () => { window.clearInterval(eventsTimer); window.clearInterval(recoveryTimer); };
  }, [selectedId, view, refreshSnapshot]);

  const runAction = useCallback(async (label: string, action: () => Promise<unknown>) => {
    if (busyLabel) return;
    setBusyLabel(label); setNotice(null);
    try {
      await action();
      if (selectedId && label !== "刷新") await api.reconcileWorkflow(selectedId);
      setNotice({tone: "good", message: `${label}已由后端记录。`});
      await Promise.all([refreshProjects(selectedId), refreshSnapshot(selectedId), refreshSystem()]);
    } catch (error) {
      setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)});
    } finally { setBusyLabel(null); }
  }, [busyLabel, refreshProjects, refreshSnapshot, refreshSystem, selectedId]);

  async function selectProject(projectId: string) {
    setSelectedId(projectId); updateUrl(projectId); setView("project"); setSnapshot(null); setNotice(null);
  }

  async function projectCreated(project: ProjectDetail) {
    await refreshProjects(project.project.project_id);
    setSelectedId(project.project.project_id); updateUrl(project.project.project_id); setView("project");
    await refreshSnapshot(project.project.project_id);
  }

  return <div className="app-shell">
    <aside className="project-sidebar">
      <div className="brand"><div className="brand-glyph">AR</div><div><strong>AutoResearch</strong><span>v0.2 · local lab</span></div></div>
      <button type="button" className="new-project-button" onClick={() => {setView("create"); setNotice(null);}}>＋ 新建研究</button>
      <nav className="project-list" aria-label="研究项目">{projects.map(item => <button type="button" key={item.project.project_id} className={view === "project" && selectedId === item.project.project_id ? "active" : ""} onClick={() => void selectProject(item.project.project_id)}><span className={`project-mode mode-${item.project.project_type === "topic_based" ? "a" : "b"}`}>{item.project.project_type === "topic_based" ? "A" : "B"}</span><span><strong>{item.project.title}</strong><small>{titleCase(item.state.stage)}</small></span><i className={`state-dot state-${item.state.status}`} /></button>)}</nav>
      {!projects.length && !loading && <p className="sidebar-empty">还没有研究项目。</p>}
      <div className="sidebar-footer"><button type="button" className={view === "settings" ? "active" : ""} onClick={() => {setView("settings"); setNotice(null);}}>模型配置</button><div><span className={`connection-light ${health?.status === "ok" ? "online" : ""}`} /><span>{health?.status === "ok" ? "Loopback online" : "Backend unavailable"}</span></div></div>
    </aside>

    <div className="console-surface">
      <header className="topbar">
        <div><span className="eyebrow">{view === "settings" ? "Runtime configuration" : view === "create" ? "Research entrypoint" : selected ? `${selected.project.project_type === "topic_based" ? "A mode" : "B mode"} · ${titleCase(selected.state.stage)}` : "Local research runtime"}</span><h1>{view === "settings" ? "模型配置" : view === "create" ? "建立研究空间" : selected?.project.title ?? "AutoResearch 科研控制台"}</h1></div>
        <div className="topbar-meta">{selected && view === "project" && <Badge value={selected.state.status} />}{busyLabel && <span className="busy-indicator"><i />{busyLabel}…</span>}<button type="button" className="icon-button" aria-label="刷新所有后端状态" onClick={() => selectedId ? void runAction("刷新", () => refreshSnapshot(selectedId)) : void refreshSystem().catch(error => setNotice({tone: "bad", message: error instanceof Error ? error.message : String(error)}))}>↻</button></div>
      </header>

      {notice && <div className="global-notice"><InlineNotice tone={notice.tone}>{notice.message}<button type="button" aria-label="关闭提示" onClick={() => setNotice(null)}>×</button></InlineNotice></div>}
      {view === "create" && <main className="standalone-view"><ProjectCreate onCreated={projectCreated} onCancel={projects.length ? () => setView("project") : undefined} /></main>}
      {view === "settings" && <main className="standalone-view settings-view"><ProviderConsole view={llm} onChanged={refreshSystem} /></main>}
      {view === "project" && loading && <main className="loading-view"><div className="loader" /><p>正在从持久化后端恢复研究状态…</p></main>}
      {view === "project" && !loading && selected && snapshot && <ProjectWorkbench project={selected} snapshot={snapshot} runAction={runAction} />}
      {view === "project" && !loading && !selected && <main className="loading-view"><p>请选择或建立研究项目。</p></main>}
      {view === "settings" && <footer className="runtime-bar"><span>Backend {health?.version ?? "—"}</span><span>{health?.host ?? "127.0.0.1"}</span><span>{health?.conda_env ? `Conda ${health.conda_env}` : "Conda state unavailable"}</span><span title={health?.runtime_root}>{text(health?.runtime_root, "runtime root unavailable")}</span><span>{health?.llm_status ?? "LLM unknown"}</span><time>{snapshot ? dateTime(snapshot.state.updated_at) : "—"}</time></footer>}
    </div>
  </div>;
}
