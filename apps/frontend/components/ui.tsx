// Purpose: Supplies accessible, dependency-free visual primitives for the research console.
import type {ReactNode} from "react";

import {dateTime, shortId, text, titleCase} from "@/lib/format";
import type {ApiRecord} from "@/lib/types";

export function Badge({value, tone}: {value: unknown; tone?: "good" | "warn" | "bad" | "info"}) {
  const normalized = text(value).toLowerCase();
  const inferred = tone ?? (
    ["completed", "approved", "ready", "pass", "passed", "supported", "verified", "ok"].some(word => normalized.includes(word)) ? "good" :
      ["failed", "rejected", "blocked", "error", "cancelled", "contradicted"].some(word => normalized.includes(word)) ? "bad" :
        ["pending", "waiting", "paused", "insufficient", "revise", "running", "queued"].some(word => normalized.includes(word)) ? "warn" : "info"
  );
  return <span className={`badge badge-${inferred}`}>{titleCase(value)}</span>;
}

export function Section({title, eyebrow, action, children, className = ""}: {
  title: string; eyebrow?: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return <section className={`panel ${className}`}>
    <header className="panel-heading">
      <div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div>
      {action && <div className="panel-action">{action}</div>}
    </header>
    {children}
  </section>;
}

export function Empty({children = "当前阶段尚无持久化记录。"}: {children?: ReactNode}) {
  return <div className="empty"><span aria-hidden="true">○</span><p>{children}</p></div>;
}

export function Metric({label, value, hint}: {label: string; value: ReactNode; hint?: ReactNode}) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}

export function FormField({label, hint, children, wide = false}: {label: string; hint?: string; children: ReactNode; wide?: boolean}) {
  return <label className={`form-field ${wide ? "field-wide" : ""}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function InlineNotice({tone = "info", children}: {tone?: "info" | "good" | "warn" | "bad"; children: ReactNode}) {
  return <div className={`notice notice-${tone}`}>{children}</div>;
}

export function AuditJson({value, label = "查看完整审计记录"}: {value: unknown; label?: string}) {
  return <details className="audit-json"><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>;
}

export function RecordList({items, empty, render}: {items: ApiRecord[]; empty?: string; render: (item: ApiRecord, index: number) => ReactNode}) {
  if (!items.length) return <Empty>{empty}</Empty>;
  return <div className="record-list">{items.map((item, index) => render(item, index))}</div>;
}

export function RecordCard({item, idKeys, titleKeys, children}: {
  item: ApiRecord; idKeys: string[]; titleKeys: string[]; children?: ReactNode;
}) {
  const title = titleKeys.map(key => item[key]).find(value => typeof value === "string") ?? "记录";
  const id = idKeys.map(key => item[key]).find(value => typeof value === "string");
  const status = item.status ?? item.decision ?? item.outcome ?? item.recommendation;
  return <article className="record-card">
    <div className="record-card-top"><div><strong>{text(title)}</strong>{id && <code>{shortId(id)}</code>}</div>{status !== undefined && <Badge value={status} />}</div>
    {children}
    {Boolean(item.created_at) && <small className="timestamp">{dateTime(item.created_at)}</small>}
    <AuditJson value={item} />
  </article>;
}

export function Segmented<T extends string>({value, options, onChange, label}: {
  value: T; options: Array<{value: T; label: string}>; onChange: (value: T) => void; label: string;
}) {
  return <div className="segmented" role="group" aria-label={label}>{options.map(option =>
    <button key={option.value} type="button" className={value === option.value ? "active" : ""} onClick={() => onChange(option.value)}>{option.label}</button>
  )}</div>;
}
