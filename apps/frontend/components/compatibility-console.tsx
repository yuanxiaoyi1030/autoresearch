// Purpose: Exposes the explicit, read-only v0.1 weight-decay compatibility importer.
"use client";

import {useCallback, useEffect, useState} from "react";

import {api} from "@/lib/api";
import type {
  BuiltinStudyDescriptor, CompatibilityVerification, V01CompatibilityImport
} from "@/lib/types";
import {AuditJson, Badge, InlineNotice, Section} from "./ui";

export function CompatibilityConsole() {
  const [builtins, setBuiltins] = useState<BuiltinStudyDescriptor[]>([]);
  const [imports, setImports] = useState<V01CompatibilityImport[]>([]);
  const [verification, setVerification] = useState<CompatibilityVerification | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [builtinValues, importValues] = await Promise.all([
      api.listBuiltins(), api.listV01CompatibilityImports(),
    ]);
    setBuiltins(builtinValues); setImports(importValues);
  }, []);

  useEffect(() => { void refresh().catch(error => setMessage(
    error instanceof Error ? error.message : String(error)
  )); }, [refresh]);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true); setMessage(null);
    try { await action(); setMessage(success); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  const builtin = builtins.find(item => item.builtin_id === "builtin/weight_decay_v1");
  const evidencePolicy = builtin?.evidence_policy ?? "legacy_hash_verified_not_reproduced";
  return <Section title="v0.1 兼容导入" eyebrow="Read-only compatibility">
    <InlineNotice>
      仅从 v0.1 运行目录读取并校验固定的 weight-decay 六运行队列；复制到 v0.2 后才允许查看，
      不执行 v0.1 代码，也不把旧结果标记为已复现实验。
    </InlineNotice>
    <div className="subsection-title"><div><strong>{builtin?.display_name ?? "builtin/weight_decay_v1"}</strong>
      <p>{builtin?.execution_mode ?? "正在读取内置兼容定义…"}</p></div>
      <Badge value={evidencePolicy} /></div>
    <div className="button-row"><button type="button" className="button-primary" disabled={busy || !builtin}
      onClick={() => run(() => api.importV01WeightDecay(), "v0.1 只读导入已完成或命中同一幂等记录。")}>
      校验并导入 v0.1 固定实验
    </button></div>
    {imports.map(item => <article className="route-card" key={item.compatibility_import_id}>
      <div className="subsection-title"><div><strong>{item.compatibility_import_id}</strong>
        <p>{item.runs.length} runs · {item.artifacts.length} artifacts · {item.source_runtime_root}</p></div>
        <Badge value={item.source_integrity_unchanged ? item.status : "source-changed"} /></div>
      <div className="button-row"><button type="button" className="button-quiet" disabled={busy}
        onClick={() => run(async () => setVerification(
          await api.verifyV01CompatibilityImport(item.compatibility_import_id)
        ), "导入副本的 manifest 与 Artifact 哈希已重新核验。")}>重新校验副本</button></div>
    </article>)}
    {!imports.length && <p>尚无 v0.1 兼容导入记录。</p>}
    {verification && <AuditJson value={verification} label="兼容导入校验结果" />}
    {message && <InlineNotice tone={message.includes("失败") ? "bad" : "info"}>{message}</InlineNotice>}
  </Section>;
}
