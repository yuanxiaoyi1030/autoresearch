// Purpose: Configures model routes and process-memory credentials without browser persistence.
"use client";

import {useEffect, useState} from "react";

import {api} from "@/lib/api";
import type {ApiRecord, LLMConfigView, LLMRuntimeConfig, LLMStage, ModelRoute, ProviderType} from "@/lib/types";
import {Badge, FormField, InlineNotice, Section} from "./ui";

const STAGES: Array<{id: LLMStage; label: string}> = [
  {id: "project_understanding", label: "项目理解"}, {id: "literature", label: "文献研究"},
  {id: "hypothesis_planning", label: "研究设计"}, {id: "experiment_code", label: "实验建模与代码"},
  {id: "analysis", label: "分析"}, {id: "research_review", label: "科研评审"}, {id: "writer", label: "论文写作"}
];

const PROVIDERS: Array<{value: ProviderType; label: string}> = [
  {value: "openai_compatible", label: "OpenAI compatible"}, {value: "openai", label: "OpenAI"},
  {value: "local_openai_compatible", label: "Local compatible"}, {value: "anthropic", label: "Anthropic"},
  {value: "gemini", label: "Gemini"}, {value: "fake", label: "Fake（仅离线）"}
];

const EMPTY_ROUTE: ModelRoute = {
  model: {
    provider_id: "primary", provider_type: "openai_compatible", model: "",
    base_url: "https://api.openai.com/v1", protocol: "responses", temperature: 0.2,
    max_output_tokens: 4000, timeout_seconds: 60, retry_count: 2,
    credential_required: true, input_cost_per_million_tokens: null,
    output_cost_per_million_tokens: null
  },
  budget: {max_calls: 8, max_input_tokens: 100000, max_output_tokens: 32000,
    max_total_tokens: 132000, max_cost_usd: null}
};

type ConnectionTestResult = ApiRecord & {
  ok: boolean;
  model: string;
  latency_ms: number;
  status: string;
  error?: string | null;
};

function cloneRoute(route?: ModelRoute | null): ModelRoute {
  return structuredClone(route ?? EMPTY_ROUTE);
}

function numberOrNull(value: string): number | null {
  return value.trim() ? Number(value) : null;
}

function providerNeedsCredential(providerType: ProviderType): boolean {
  return !["local_openai_compatible", "fake"].includes(providerType);
}

function providerBaseUrl(providerType: ProviderType): string | null {
  if (providerType === "openai") return "https://api.openai.com/v1";
  if (providerType === "fake") return "http://offline.invalid/v1";
  return null;
}

function normalizeStageRoutes(config: LLMRuntimeConfig, defaultRoute: ModelRoute): LLMRuntimeConfig {
  const stages: LLMRuntimeConfig["stages"] = {};
  for (const [stage, route] of Object.entries(config.stages) as Array<[LLMStage, ModelRoute]>) {
    stages[stage] = {
      model: {
        ...defaultRoute.model,
        model: route.model.model,
        temperature: route.model.temperature,
        max_output_tokens: route.model.max_output_tokens,
        timeout_seconds: route.model.timeout_seconds,
        retry_count: route.model.retry_count
      },
      budget: structuredClone(defaultRoute.budget)
    };
  }
  return {...config, default_route: defaultRoute, stages};
}

function AdvancedParameters({route, onChange}: {route: ModelRoute; onChange: (route: ModelRoute) => void}) {
  const model = route.model;
  const update = (key: keyof ModelRoute["model"], value: unknown) => onChange({...route, model: {...model, [key]: value}});
  return <details className="advanced-settings">
    <summary>高级参数</summary>
    <div className="form-grid">
      <FormField label="Temperature"><input type="number" min="0" max="2" step="0.1" value={model.temperature ?? ""} onChange={event => update("temperature", numberOrNull(event.target.value))} /></FormField>
      <FormField label="单次输出上限"><input type="number" min="1" value={model.max_output_tokens} onChange={event => update("max_output_tokens", Number(event.target.value))} /></FormField>
      <FormField label="超时（秒）"><input type="number" min="1" max="600" value={model.timeout_seconds} onChange={event => update("timeout_seconds", Number(event.target.value))} /></FormField>
      <FormField label="重试次数"><input type="number" min="0" max="8" value={model.retry_count} onChange={event => update("retry_count", Number(event.target.value))} /></FormField>
    </div>
  </details>;
}

function DefaultRouteEditor({route, providers, apiKey, configured, busy, onChange, onApiKeyChange, onSaveCredential, onClearCredential}: {
  route: ModelRoute;
  providers: LLMConfigView["providers"];
  apiKey: string;
  configured: boolean;
  busy: boolean;
  onChange: (route: ModelRoute) => void;
  onApiKeyChange: (value: string) => void;
  onSaveCredential: () => void;
  onClearCredential: () => void;
}) {
  const model = route.model;
  const availability = new Map(providers.map(provider => [provider.provider_type, provider.available]));
  const update = (key: keyof ModelRoute["model"], value: unknown) => onChange({...route, model: {...model, [key]: value}});
  const changeProvider = (providerType: ProviderType) => {
    const fixedUrl = providerBaseUrl(providerType);
    onChange({...route, model: {...model,
      provider_type: providerType,
      base_url: fixedUrl ?? (providerType === model.provider_type ? model.base_url : ""),
      credential_required: providerNeedsCredential(providerType)
    }});
  };
  const credentialLabel = model.credential_required ? (configured ? "已配置" : "未配置") : "无需配置";
  return <>
    <div className="form-grid">
      <FormField label="Provider 类型"><select value={model.provider_type} onChange={event => changeProvider(event.target.value as ProviderType)}>
        {PROVIDERS.map(provider => {
          const available = availability.get(provider.value);
          if (providers.length && !available && provider.value !== model.provider_type) return null;
          return <option key={provider.value} value={provider.value} disabled={available === false}>{provider.label}{available === false ? "（暂不可用）" : ""}</option>;
        })}
      </select></FormField>
      <FormField label="模型"><input value={model.model} onChange={event => update("model", event.target.value)} placeholder="例如 gpt-5" required /></FormField>
      <FormField label="协议"><select value={model.protocol} onChange={event => update("protocol", event.target.value as "chat_completions" | "responses")}><option value="responses">Responses</option><option value="chat_completions">Chat Completions</option></select></FormField>
      <FormField label="Base URL"><input value={model.base_url} onChange={event => update("base_url", event.target.value)} required /></FormField>
      <div className="form-field field-wide credential-editor">
        <div className="credential-title"><label htmlFor="default-api-key">API Key</label><Badge value={credentialLabel} tone={configured ? "good" : model.credential_required ? "warn" : "info"} /></div>
        <div className="credential-controls">
          <input id="default-api-key" aria-label="API Key" type="password" autoComplete="off" value={apiKey} onChange={event => onApiKeyChange(event.target.value)} placeholder={model.credential_required ? "输入后提交到后端内存" : "当前 Provider 无需凭证"} disabled={!model.credential_required} />
          <button type="button" className="button-primary" disabled={busy || !apiKey || !model.credential_required} onClick={onSaveCredential}>提交</button>
          <button type="button" className="button-quiet" disabled={busy || !configured} onClick={onClearCredential}>清除</button>
        </div>
        <small>Key 只保存在后端进程内，提交后立即清空输入。</small>
      </div>
    </div>
    <AdvancedParameters route={route} onChange={onChange} />
  </>;
}

function StageRouteEditor({route, onChange}: {route: ModelRoute; onChange: (route: ModelRoute) => void}) {
  return <div className="stage-route-editor">
    <FormField label="模型"><input value={route.model.model} onChange={event => onChange({...route, model: {...route.model, model: event.target.value}})} placeholder="例如 gpt-5" required /></FormField>
    <AdvancedParameters route={route} onChange={onChange} />
  </div>;
}

export function ProviderConsole({view, onChanged}: {view: LLMConfigView | null; onChanged: () => Promise<void>}) {
  const [config, setConfig] = useState<LLMRuntimeConfig>({default_route: cloneRoute(), stages: {}, offline_mode: false});
  const [apiKey, setApiKey] = useState("");
  const [testStage, setTestStage] = useState<LLMStage>("project_understanding");
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => { if (view) setConfig(structuredClone(view.config)); }, [view]);

  const defaultRoute = config.default_route ?? cloneRoute();
  const providerId = defaultRoute.model.provider_id;
  const credential = view?.status.credentials.find(item => String(item.provider_id) === providerId);
  const credentialConfigured = Boolean(credential?.configured);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage(null);
    try { await action(); setMessage(success); await onChanged(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function saveCredential() {
    const volatileKey = apiKey;
    setApiKey("");
    await run(() => api.saveCredential(providerId, volatileKey), "API Key 已提交到后端进程内存。");
  }

  async function testConnection() {
    setBusy(true); setMessage(null); setTestResult(null);
    try {
      const value = await api.testConnection(testStage) as ConnectionTestResult;
      setTestResult(value);
      await onChanged();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally { setBusy(false); }
  }

  return <Section title="模型路由" eyebrow="LLM configuration" className="settings-main" action={<Badge value={view?.status.status ?? "loading"} />}>
    <InlineNotice tone={view?.status.ready ? "good" : "warn"}>{view?.status.detail ?? "正在读取后端配置…"}</InlineNotice>
    <div className="subsection-title"><div><strong>默认路由</strong><p>未单独覆盖的科研阶段使用这里的连接和模型。</p></div><label className="switch"><input type="checkbox" checked={config.offline_mode} onChange={event => setConfig({...config, offline_mode: event.target.checked})} /><span>离线模式</span></label></div>
    <DefaultRouteEditor route={defaultRoute} providers={view?.providers ?? []} apiKey={apiKey} configured={credentialConfigured} busy={busy}
      onChange={route => setConfig({...config, default_route: route})} onApiKeyChange={setApiKey} onSaveCredential={() => void saveCredential()}
      onClearCredential={() => void run(() => api.clearCredential(providerId), "后端进程内凭证已清除。")} />

    <div className="stage-route-list"><div className="subsection-title"><div><strong>阶段覆盖</strong><p>阶段继承默认连接，只覆盖模型和高级参数。</p></div></div>
      {STAGES.map(stage => {
        const override = config.stages[stage.id];
        return <details className="route-card" key={stage.id} open={Boolean(override)}><summary><span>{stage.label}</span><span>{override ? override.model.model || "未填写模型" : "继承默认路由"}</span></summary>
          <label className="switch"><input type="checkbox" checked={Boolean(override)} onChange={event => {
            const stages = {...config.stages};
            if (event.target.checked) stages[stage.id] = cloneRoute(defaultRoute); else delete stages[stage.id];
            setConfig({...config, stages});
          }} /><span>使用阶段独立模型</span></label>
          {override && <StageRouteEditor route={override} onChange={route => setConfig({...config, stages: {...config.stages, [stage.id]: route}})} />}
        </details>;
      })}
    </div>

    <div className="button-row"><button className="button-primary" disabled={busy} onClick={() => void run(() => api.saveLLMConfig(normalizeStageRoutes(config, defaultRoute)), "模型配置已保存到后端运行时。")} type="button">保存模型配置</button></div>

    <div className="subsection-title"><div><strong>连接测试</strong><p>测试所选阶段最终生效的模型路由。</p></div></div>
    <div className="connection-test-row">
      <FormField label="测试阶段"><select value={testStage} onChange={event => setTestStage(event.target.value as LLMStage)}>{STAGES.map(stage => <option key={stage.id} value={stage.id}>{stage.label}</option>)}</select></FormField>
      <button type="button" className="button-primary" disabled={busy} onClick={() => void testConnection()}>运行连接测试</button>
    </div>
    {testResult && <InlineNotice tone={testResult.ok ? "good" : "bad"}>{testResult.ok
      ? `连接成功 · ${testResult.model} · ${testResult.latency_ms} ms`
      : `连接失败 · ${testResult.error ?? testResult.status}`}</InlineNotice>}
    {message && <InlineNotice tone={message.includes("失败") || message.includes("missing") ? "bad" : "info"}>{message}</InlineNotice>}
  </Section>;
}
