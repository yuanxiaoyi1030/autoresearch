// Purpose: Proves the local frontend exposes required APIs without browser-secret or execution surfaces.
import assert from "node:assert/strict";
import {readFileSync, readdirSync, statSync} from "node:fs";
import {join, relative} from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1");

function sourceFiles(directory) {
  return readdirSync(directory).flatMap(name => {
    const path = join(directory, name);
    if (["node_modules", ".next"].includes(name)) return [];
    return statSync(path).isDirectory() ? sourceFiles(path) : /\.(ts|tsx|css|json|mjs)$/.test(name) ? [path] : [];
  });
}

function read(path) { return readFileSync(join(root, path), "utf8"); }

test("development and production servers bind only to loopback", () => {
  const pkg = JSON.parse(read("package.json"));
  assert.match(pkg.scripts.dev, /--hostname 127\.0\.0\.1/);
  assert.match(pkg.scripts.start, /--hostname 127\.0\.0\.1/);
  const config = read("next.config.ts");
  assert.match(config, /loopbackHosts/);
  assert.match(config, /127\.0\.0\.1:8100/);
  assert.match(config, /must use an HTTP\(S\) loopback host/);
  const client = read("lib/api.ts");
  assert.match(client, /NEXT_PUBLIC_AUTORESEARCH_V0_2_API_ORIGIN/);
  assert.match(client, /loopbackHosts/);
  assert.match(client, /fetch\(backendUrl\(path\)/);
});

test("API key remains volatile browser component state", () => {
  const all = sourceFiles(root).map(path => readFileSync(path, "utf8")).join("\n");
  for (const forbidden of ["local" + "Storage", "session" + "Storage", "indexed" + "DB", "document." + "cookie"]) {
    assert.equal(all.includes(forbidden), false, `forbidden browser persistence: ${forbidden}`);
  }
  const provider = read("components/provider-console.tsx");
  assert.match(provider, /type="password" autoComplete="off"/);
  assert.match(provider, /setApiKey\(""\)/);
  assert.match(provider, /saveCredential\(providerId, volatileKey\)/);
});

test("model configuration keeps only user-facing route controls", () => {
  const consoleSource = read("components/research-console.tsx");
  const provider = read("components/provider-console.tsx");
  const styles = read("app/globals.css");
  assert.match(consoleSource, />模型配置<\/button>/);
  assert.match(consoleSource, /view === "settings" \? "模型配置"/);
  assert.doesNotMatch(consoleSource, /<CompatibilityConsole/);
  assert.doesNotMatch(consoleSource, /api\.getUsage\(\)/);
  for (const hidden of [
    "Provider ID", "输入价格 / 百万 token", "输出价格 / 百万 token", "阶段调用预算",
    "总 token 预算", "输入 token 预算", "输出 token 预算", "费用预算（USD）", "凭证要求",
    "Provider 能力", "Token 与费用", "v0.1 兼容导入"
  ]) assert.equal(provider.includes(`label="${hidden}"`) || provider.includes(`title="${hidden}"`), false, hidden);
  assert.equal(provider.match(/>运行连接测试<\/button>/g)?.length, 1);
  assert.match(provider, /\.\.\.defaultRoute\.model/);
  assert.match(provider, /budget: structuredClone\(defaultRoute\.budget\)/);
  assert.match(provider, /model: route\.model\.model/);
  assert.doesNotMatch(provider, /AuditJson/);
  assert.match(styles, /\.button-row \.button-primary/);
});

test("overview keeps only research status and progress", () => {
  const workbench = read("components/project-workbench.tsx");
  assert.match(workbench, /title="当前研究状态"/);
  assert.match(workbench, /title="研究进展"/);
  for (const hidden of ["状态修订", "失败 \/ 恢复记录", "最近活动", "需要注意", "Durable event journal", "Failures are retained"]) {
    assert.equal(workbench.includes(hidden), false, hidden);
  }
  for (const metric of ["文献来源", "证据条目", "实验运行", "分析结果", "科研评审", "论文产物"]) {
    assert.ok(workbench.includes(`label="${metric}"`), metric);
  }
});

test("research creation captures essential goals and creates the first understanding", () => {
  const create = read("components/project-create.tsx");
  for (const field of ["项目名称", "研究目标", "已有项目目录", "补充要求"]) {
    assert.ok(create.includes(`label="${field}"`) || create.includes(`>${field}`), field);
  }
  assert.match(create, /建议使用英文描述/);
  assert.match(create, /补充要求（可选）/);
  assert.match(create, /await api\.understand/);
  assert.match(create, /research_objectives: \[objective\.trim\(\)\]/);
  assert.match(create, /import_id: imported\?\.import_id \?\? null/);
  assert.doesNotMatch(create, /label="研究 Topic"/);
});

test("project understanding shows results and goal correction without audit JSON", () => {
  const workbench = read("components/project-workbench.tsx");
  const understanding = workbench.slice(workbench.indexOf("function UnderstandingPanel"), workbench.indexOf("function LiteraturePanel"));
  assert.match(understanding, /title="系统理解结果"/);
  assert.match(understanding, /修正研究目标/);
  assert.match(understanding, /保存并重新理解/);
  assert.match(understanding, /\.\.\.userConstraints, research_objectives: splitLines\(objective\)/);
  for (const hidden of ["修改研究目标与约束", "计算预算", "时间与审批约束", "允许依赖（每行一项）", "输出要求（每行一项）", "允许文献阶段访问网络"]) {
    assert.equal(understanding.includes(hidden), false, hidden);
  }
  assert.doesNotMatch(understanding, /<AuditJson/);
});

test("literature view keeps only user-facing research evidence", () => {
  const workbench = read("components/project-workbench.tsx");
  for (const section of ["文献检索", "文献来源", "证据矩阵", "研究缺口"]) {
    assert.ok(workbench.includes(`title="${section}"`), section);
  }
  for (const hidden of ["Literature Multi-Agent", "真实来源与定位", "Search attempts", "Evidence Reviewer", "Matrix revision", "JSON.stringify(evidence.locator)"]) {
    assert.equal(workbench.includes(hidden), false, hidden);
  }
  assert.match(workbench, /snapshot\.literature\.sources\.slice\(0, 5\)/);
  assert.match(workbench, /查看全部（\$\{snapshot\.literature\.sources\.length\}）/);
  assert.match(workbench, /prioritizedEvidence\.slice\(0, 5\)/);
  assert.match(workbench, /core_support: 0, contrast: 1, method: 2, background: 3/);
  assert.match(workbench, /查看全部证据（\$\{snapshot\.literature\.evidence\.length\}）/);
  assert.match(workbench, /snapshot\.literature\.gaps\.slice\(0, 5\)/);
  assert.match(workbench, /查看全部缺口（\$\{snapshot\.literature\.gaps\.length\}）/);
  assert.doesNotMatch(workbench, /证据质量提示/);
});

test("research design view follows the question-to-approval flow without technical identifiers", () => {
  const workbench = read("components/project-workbench.tsx");
  const planning = workbench.slice(workbench.indexOf("function PlanningPanel"), workbench.indexOf("function ArtifactGallery"));
  assert.match(workbench, /id: "planning", label: "研究设计"/);
  for (const section of ["研究问题", "预计答案", "实验计划", "当前审批"]) {
    assert.ok(planning.includes(`title="${section}"`), section);
  }
  assert.match(planning, /generatedResearchQuestion/);
  assert.match(planning, /LLM 推荐/);
  assert.match(planning, /查看其他预计答案/);
  assert.match(planning, /selectedCandidate/);
  assert.match(planning, /primaryMetrics/);
  assert.match(planning, /conditions\.map/);
  assert.match(planning, /\["blocking", "major"\]/);
  assert.match(planning, /批准研究问题与预计答案/);
  for (const hidden of ["最终假设", "待处理问题", "审计记录", "Revision", "content_hash", "approval_id", "provenance", "<AuditJson", "<code"]) {
    assert.equal(planning.includes(hidden), false, hidden);
  }
});

test("typed client covers the complete research workflow", () => {
  const client = read("lib/api.ts");
  const required = [
    "/api/llm/config", "/api/llm/credentials/", "/api/llm/connection-tests", "/api/llm/usage",
    "/api/builtins", "/api/compatibility/v0.1/imports", "/weight-decay-v1", "/verify",
    "/api/projects", "/imports", "/understanding", "/reuse-assessment", "/code-lineage",
    "/visualization-profiles", "/figure-specs", "/literature", "/hypotheses", "/decision",
    "/experiment-plans", "/formal-experiment-gate", "/implementation-revisions", "/diff",
    "/studies", "/runs", "/logs", "/artifacts/", "/analyses", "/verifications",
    "/scientific-reviews", "/research-reviews", "/evidence-claims", "/papers", "/paper-agent-runs"
  ];
  for (const path of required) assert.ok(client.includes(path), `missing API contract ${path}`);
  for (const action of ["pause", "resume", "cancel"]) assert.ok(client.includes(`\"${action}\"`), `missing run control ${action}`);
});

test("UI restores scientific state from backend and has no arbitrary execution form", () => {
  const consoleSource = read("components/research-console.tsx");
  const workbench = read("components/project-workbench.tsx");
  const compatibility = read("components/compatibility-console.tsx");
  assert.match(consoleSource, /loadProjectSnapshot/);
  assert.match(consoleSource, /listEvents/);
  assert.match(consoleSource, /setInterval/);
  assert.match(workbench, /Legacy Reuse Assessment/);
  assert.match(workbench, /证据矩阵/);
  assert.match(workbench, /实现 Diff/);
  assert.match(workbench, /Top-conference writing team/);
  assert.match(compatibility, /read-only v0\.1 weight-decay compatibility importer/);
  assert.match(compatibility, /legacy_hash_verified_not_reproduced/);
  assert.doesNotMatch(consoleSource + workbench, /name=["'](?:shell|command|python|interpreter)["']/i);
});

test("initial planning generations do not send revision-only feedback", () => {
  const workbench = read("components/project-workbench.tsx");
  const planning = workbench.slice(workbench.indexOf("function PlanningPanel"), workbench.indexOf("function ArtifactGallery"));
  assert.match(planning, /generateHypotheses\(projectId, null, \[\]\)/);
  assert.match(planning, /generatePlan\(projectId, String\(hypothesis\?\.hypothesis_revision_id\), null, \[\]\)/);
  assert.match(planning, /generateHypotheses\(projectId, id\(hypothesis, "hypothesis_revision_id"\) \|\| null, \[feedback\]\)/);
  assert.match(planning, /generatePlan\(projectId, String\(hypothesis\?\.hypothesis_revision_id\), id\(plan, "plan_revision_id"\) \|\| null, \[feedback\]\)/);
});

test("v0.2 sources do not reference v0.1 build output", () => {
  for (const path of sourceFiles(root)) {
    const relativePath = relative(root, path);
    if (relativePath.startsWith("tests")) continue;
    const source = readFileSync(path, "utf8");
    assert.equal(source.includes("v_0_1/.next"), false, relativePath);
    assert.equal(source.includes("v_0_1\\.next"), false, relativePath);
  }
});
