# AutoResearch v0.2 开发计划

## 1. 项目定位

AutoResearch v0.2 将 v0.1 的 weight-decay 专用验收系统升级为支持任意研究 Topic 和任意允许导入项目的通用、可审计科研平台。

v0.2 的核心目标：

1. 解除 Literature、Hypothesis、Experiment Plan、Experiment、Critic 和 Writer 对 weight decay 的绑定。
2. 支持根据用户 Topic、约束和已有项目材料动态开展研究。
3. 接入真实 LLM Provider，允许用户安全配置 API key、模型和预算。
4. 在适合的科研阶段引入数量适中、职责明确的 Multi-Agent。
5. 建立通用 Study、Run、Metric、Analysis、Evidence、Code Lineage 和 Visualization 数据模型。
6. B 模式优先继承已有项目的实验设计、代码结构和图片风格，并在可审计边界内补充实验。
7. 生成证据约束、接近 NeurIPS、ICML、ICLR 等顶会结构的完整论文。
8. 保留失败实验、负结果和证据不足结果，确保研究过程可追踪、可恢复、可复现。

weight-decay Study 将作为内置示例和回归测试保留，但不再控制系统主流程。

---

## 2. 工程与安全边界

### 2.1 必须遵守

- 所有 Python 后端、测试、worker、runner 和实验命令必须先执行 `conda activate d2l`。
- 未经用户明确批准，不安装、删除或升级任何依赖。
- Web/API 只能监听 loopback 地址。
- 不删除或覆盖已有研究、失败记录、负结果和证据不足记录。
- `D:\ml_project\coscientist` 始终只读。
- 导入只能读取和复制，不能直接执行导入项目中的代码、Notebook 或二进制文件。
- 所有导入路径必须解析并限制在 `allowed_import_roots` 内。
- v0.2 使用独立的 `D:\code\work\autoresearch\v_0_2_runtime_data`，不得与 v0.1 runtime data 混用。
- API key 不得进入日志、数据库明文、事件、Job payload、Artifact、Prompt metadata 或实验子进程环境。
- Agent 不得绕过 Workflow、审批、预算、路径和执行权限。
- 正式实验必须绑定已批准 Plan 的 revision 和 hash。
- 原始导入快照、旧实验、旧图片和旧结论必须保留 provenance，不能静默升级为已验证证据。

### 2.2 非目标

v0.2 不承诺：

- 自动保证论文被顶会录用。
- 在证据不足时生成肯定性科研结论。
- 自动执行任意导入代码。
- 允许 LLM 直接控制任意 shell、解释器或依赖安装。
- 自动扩大实验规模或更换依赖。
- 用 Agent 共识代替用户审批。
- 用文字扩写掩盖实验、创新性或证据不足。
- 为了统一新系统而覆盖用户已有代码、图表或失败记录。

---

## 3. 科研状态机

v0.2 采用以下可持久化、暂停、恢复和审计的状态：

```text
INITIALIZING
    ↓
PROJECT_UNDERSTANDING
    ↓
LITERATURE
    ↓
HYPOTHESIS
    ↓
WAIT_HYPOTHESIS_APPROVAL
    ↓
EXPERIMENT_PLANNING
    ↓
WAIT_PLAN_APPROVAL
    ↓
EXPERIMENT_IMPLEMENTATION
    ↓
EXPERIMENT
    ↓
ANALYSIS
    ↓
RESEARCH_REVIEW
    ↓
REPORT_PLANNING
    ↓
REPORT_WRITING
    ↓
REPORT_REVIEW
    ↓
COMPLETED
```

允许的反馈循环：

- Hypothesis 被拒绝后返回 `HYPOTHESIS`。
- Plan 被拒绝后返回 `EXPERIMENT_PLANNING`。
- 实现发现设计不可执行时返回 `EXPERIMENT_PLANNING`。
- Analysis 发现批准范围内实验缺失时返回 `EXPERIMENT`。
- Research Review 发现方法问题时返回 `EXPERIMENT_PLANNING`。
- Research Review 发现实验缺失时返回 `EXPERIMENT`。
- Report Review 发现写作问题时返回 `REPORT_WRITING`。
- Report Review 发现证据问题时返回 `RESEARCH_REVIEW`、`EXPERIMENT` 或 `EXPERIMENT_PLANNING`。

新增实验、改变指标、扩大预算、修改实验语义或增加依赖时，必须创建新 Plan revision 并重新审批。

---

## 4. A/B 模式总体流程

### 4.1 A 模式：从任意 Topic 开始

```text
用户 Topic 与约束
    ↓
通用 Project Understanding
    ↓
Literature Multi-Agent
    ↓
Hypothesis & Planning Multi-Agent
    ↓
用户审批
    ↓
实验实现、执行、分析与评审
    ↓
论文写作与审查
```

A 模式不得预设 weight decay、网络结构、数据集、指标或实验方法。所有研究内容必须来自用户 Topic、检索证据、约束和经审批的研究设计。

### 4.2 B 模式：继承已有项目

```text
已有项目只读快照
    ↓
Project Understanding
    ↓
已有研究、代码、实验、结果和图片设计解析
    ↓
Legacy Reuse Assessment
    ↓
选择：直接适配 / 局部重构 / 安全重实现
    ↓
Literature、Hypothesis 与 Planning Multi-Agent
    ↓
用户审批复用范围和补充实验
    ↓
复制候选代码到 v0.2 Workspace
    ↓
Research Engineer 适配副本
    ↓
Verification Auditor 核对语义和血缘
    ↓
Smoke Test
    ↓
Deterministic Experiment Runtime
    ↓
按已有视觉规范重新生成图片并补充分析
```

B 模式的原则不是直接运行旧代码，也不是忽略旧代码重新生成，而是最大限度继承已有研究设计、实现逻辑和视觉风格，在只读、安全、可审计和用户审批的前提下进行必要适配。

---

## 5. 系统总体架构

```text
用户 Topic / 已有项目
        ↓
Project Understanding
        ↓
Literature Multi-Agent
        ↓
Hypothesis & Planning Multi-Agent
        ↓
用户审批
        ↓
Experiment Implementation & Analysis Multi-Agent
        ↓
Deterministic Experiment Runtime
        ↓
Independent Research Review Multi-Agent
        ↓
Paper Writing Multi-Agent
        ↓
Evidence / Policy Guard
        ↓
ResearchState + Artifacts + Paper
```

系统由三层控制结构组成。

### 5.1 Deterministic Workflow Coordinator

Coordinator 是代码组件，不是 LLM Agent，负责：

- Workflow 状态转换；
- Agent 调度与并发限制；
- token、调用次数、费用和时间预算；
- 工具和权限控制；
- Job 持久化和幂等；
- 失败重试；
- pause、resume 和 cancel；
- 用户审批门禁；
- Agent 结果保存和版本管理。

Coordinator 不做科研判断，也不撰写论文。

### 5.2 Stage Lead Agent

每个 Multi-Agent 环节配置一个 Lead Agent，负责：

- 分解阶段任务；
- 协调专业 Agent；
- 维护研究目标和上下文一致性；
- 汇总候选结果；
- 处理意见冲突；
- 生成唯一候选阶段产物；
- 根据 Reviewer 意见修订。

Lead 可以执行部分专业工作，但不能最终批准自己生成的产物。

### 5.3 Independent Reviewer

Reviewer 必须：

- 使用独立上下文；
- 不参与被审查内容的首次生成；
- 只读取正式候选产物和证据；
- 输出结构化缺陷；
- 不直接修改原始证据；
- 将问题分为 blocking、major 和 minor。

Research Review 阶段的 Meta Reviewer 是例外：它可以领导 Reviewer Team 并汇总评审，但不得参与原研究或论文的首次生成。

---

## 6. 通用研究数据模型

### 6.1 ResearchContext

统一描述：

- 用户 Topic 和约束；
- 导入项目摘要；
- 数据、代码、Notebook 和配置清单；
- 已有论文、实验、图片和结果；
- 已知问题和缺失证据；
- 算力、时间、网络和依赖预算；
- provenance 和 verification status。

### 6.2 Hypothesis

Hypothesis 必须包含：

- research question；
- falsifiable statement；
- independent variables；
- dependent variables；
- controls；
- expected observations；
- alternative explanations；
- supporting literature；
- novelty assessment；
- feasibility assessment；
- evidence gaps；
- revision provenance。

### 6.3 StudySpec

使用通用 `StudySpec` 替代专用 `WeightDecayStudyService`：

- `study_id`
- `objective`
- `hypothesis_binding`
- `baseline`
- `conditions`
- `datasets`
- `run_matrix`
- `metrics`
- `analysis_spec`
- `execution_policy`
- `resource_budget`
- `stop_criteria`
- `failure_criteria`
- `evidence_requirements`
- `plan_revision`
- `plan_hash`

### 6.4 RunSpec

每个 Run 记录：

- entrypoint；
- argument array；
- immutable config；
- seed 和 condition；
- environment；
- timeout 和 output limit；
- network policy；
- evidence eligibility；
- expected artifacts；
- code、config 和 environment hash。

### 6.5 MetricSpec 与 AnalysisSpec

MetricSpec 描述 metric name、科学定义、计算方法、方向、聚合方式、单位、Evidence 路径和有效性要求。

AnalysisSpec 描述 comparison groups、统计方法、区间、效应量、多重比较策略、失败和缺失数据处理以及 outcome decision rule。

### 6.6 CodeLineageRecord

B 模式为所有复用或派生代码记录：

- 原始 snapshot 和文件 hash；
- 派生文件和 hash；
- 适配策略；
- non-semantic 与 semantic 修改；
- 对应 Plan revision；
- Verification Auditor 的核验结果。

### 6.7 VisualizationProfile 与 FigureSpec

`VisualizationProfile` 保存已有项目或目标会议的图片规范：颜色、字体、尺寸、布局、线型、marker、DPI、输出格式和 caption 风格。

`FigureSpec` 为每张正式图片声明：用途、输入 Artifact、panel、指标、视觉规范、caption 和补充图要求。

---

## 7. LLM Provider 与用户配置

### 7.1 Provider Registry

建立统一 Provider Registry，计划支持：

1. OpenAI-compatible API；
2. OpenAI；
3. Anthropic；
4. Gemini；
5. 本地 OpenAI-compatible 服务。

每个 Provider 统一实现 structured output、tool calls、streaming、timeout、retry、usage accounting、error normalization、secret redaction 和 capability declaration。

第一阶段优先实现 OpenAI-compatible Provider，在不安装新依赖的前提下使用现有能力或标准 HTTP。

### 7.2 分阶段模型配置

用户可以分别配置：

- Project Understanding model；
- Literature model；
- Hypothesis and Planning model；
- Experiment/Code model；
- Analysis model；
- Research Review model；
- Writer model。

配置项包括 provider、model、base URL、temperature、maximum output tokens、timeout、retry count、stage call budget 和 stage cost budget。

### 7.3 API key 安全

MVP 支持环境变量，以及 UI 输入后仅保存在后端进程内存；重启后重新输入。前端只显示 configured/unconfigured 和脱敏标识。

后续可以接入 Windows Credential Manager 或 DPAPI。

禁止 localStorage 保存密钥、SQLite 明文保存密钥、Event Journal 记录密钥、API 返回密钥、Agent Prompt 携带密钥以及实验子进程继承密钥。

---

## 8. Multi-Agent 角色配置

v0.2 设置 5 个 Multi-Agent 环节：

| 环节 | Lead Agent | 专业 Agent | 独立 Reviewer | 总数 |
|---|---|---|---|---:|
| 文献研究 | Literature Lead | Lead 同时负责搜索和综合 | Evidence Reviewer | 2 |
| 假设与实验规划 | Research Design Lead | Lead 同时负责设计 | Critical Reviewer | 2 |
| 实验与分析 | Experimental Lead / Modeling Scientist | Research Engineer、Statistical Analyst | Verification Auditor、Scientific Reviewer | 5 |
| 独立科研评审 | Meta Reviewer | Methodology、Statistical、Evidence & Reproducibility Reviewers | Meta Reviewer 汇总 | 4 |
| 论文写作 | Lead Author | Technical、Citation、Presentation Editors | Top-Conference Reviewer | 5 |

默认配置：

```yaml
multi_agent:
  enabled: true
  max_parallel_agents: 2
  max_review_rounds: 2
  independent_reviewer_context: true
  preserve_rejected_outputs: true
```

角色总数不代表同时运行数量。默认每个时点最多运行 2 个 LLM Agent。未来通过 `AgentRoleRegistry` 增加角色，不修改核心 Workflow 和数据结构。

---

## 9. 文献研究 Multi-Agent

### 9.1 Literature Lead

- 将 Topic 分解为检索问题；
- 生成多组关键词和同义词；
- 搜索 arXiv、OpenAlex、Crossref 等来源；
- 执行引用追踪；
- 阅读 metadata、abstract 和允许访问的全文；
- 去重和相关性排序；
- 综合 Related Work 和 Research Gap；
- 生成 Literature Evidence Matrix。

### 9.2 Evidence Reviewer

- 独立核对论文是否真实存在；
- 检查 DOI、版本、页码和章节；
- 判断 metadata、abstract-only 或 full-text；
- 检查引用是否支持对应陈述；
- 检查是否遗漏关键相关工作；
- 阻止不可靠来源进入核心 Evidence Store。

输出包括 LiteratureSource、LiteratureEvidence、ResearchGap、SearchAttempt、Evidence Matrix 和 review report。Abstract-only 来源不得支持主要科学结论。

---

## 10. Hypothesis 与实验规划 Multi-Agent

### 10.1 Research Design Lead

- 生成并比较候选 Hypothesis；
- 评估研究价值和可执行性；
- 定义模型、baseline、变量和控制条件；
- 设计指标、实验矩阵和分析方案；
- 生成 StudySpec、RunSpec、MetricSpec 和 AnalysisSpec；
- B 模式明确哪些已有设计保留、适配或替换；
- 根据 Reviewer 和用户意见修订。

### 10.2 Critical Reviewer

- 检查创新性和可证伪性；
- 检查是否真正回答用户 Topic；
- 检查 baseline、ablation 和控制变量；
- 检查统计设计、资源和复现条件；
- 检查 B 模式对旧设计的改变是否合理；
- 查找混杂因素和替代解释；
- 输出 blocking、major 和 minor 缺陷。

Hypothesis 和 Experiment Plan 分别保留用户审批门禁。未经批准不得生成正式 runner、启动 evidence-eligible Run 或扩大实验预算。

---

## 11. B 模式代码、实验与视觉设计继承

### 11.1 Legacy Reuse Assessment

Project Understanding 必须识别：

- 研究问题和已有结论；
- 模型、数据、loss、optimizer 和训练逻辑；
- entrypoint、配置、依赖和环境；
- 已有 Run、metrics、tables 和 figures；
- plotting code 和视觉风格；
- 可复用、需适配、不可执行和证据不足部分。

输出 `LegacyReuseAssessment`，交由用户随 Plan 一并审批。

### 11.2 三种复用策略

1. `adapt_existing`：默认推荐，尽量保留模型、数据处理、loss、optimizer、实验配置、指标和 plotting code，只适配路径、Artifact、seed、配置、日志、安全边界和恢复能力。
2. `partial_refactor`：保留科学语义，重构 runner、Notebook 状态、配置、输出和绘图模块。
3. `safe_reimplementation`：原代码不完整、不安全、环境无法复现或指标不可验证时重新实现，并记录与原设计的映射和差异。

无论采用哪种策略，原目录保持只读。候选代码必须复制到 v0.2 Project Workspace，经过审查后才能执行。

### 11.3 修改分类

Non-semantic 修改包括路径、日志、Artifact 输出、配置加载、checkpoint、运行恢复和安全边界，可以作为 Implementation Revision 处理。

Semantic 修改包括模型结构、数据、loss、optimizer、超参数、baseline、指标、训练时长和统计方法，必须创建新的 Experiment Plan revision 并由用户重新审批。

### 11.4 图片继承

B 模式从已有 plotting code 和图片中提取 VisualizationProfile。旧图片保留为 `legacy/unverified`，不能自动成为新实验的证据。正式图片必须从新的已验证 Artifact 重新生成，默认遵循已有项目视觉规范，并允许在 Plan 中声明补充图。

若只有图片而没有源数据，该图片只能作为风格或初步观察参考。论文展示 legacy 图片时必须明确标注其来源和验证状态。

---

## 12. 实验与分析 Multi-Agent

### 12.1 Experimental Lead / Modeling Scientist

- 将 Hypothesis 转换为数学或计算模型；
- 明确目标函数、模型结构和实验逻辑；
- B 模式判断已有实验哪些保留、适配和补充；
- 协调工程实现、运行和统计分析；
- 处理 Agent 之间的分歧；
- 确保实现没有偏离批准 Plan；
- 汇总实验阶段候选结论。

该角色不能审核或批准自己的最终结论。

### 12.2 Research Engineer

- 实现批准的模型和实验代码；
- B 模式复制并适配候选代码副本；
- 编写数据处理、训练和评估逻辑；
- 编写 smoke test、单元测试和 runner；
- 输出结构化 metrics、figures 和 artifacts；
- 提取并实现 VisualizationProfile；
- 诊断实验失败并提出候选修复。

### 12.3 Statistical Analyst

- 执行批准的统计分析；
- 计算效应量、区间、方差和显著性；
- 分析随机种子、异常值和缺失 Run；
- 判断已有分析是否充分；
- 生成主结果、消融、表格、图片和补充分析；
- 区分支持、负结果和证据不足。

### 12.4 Verification Auditor

- 独立审查实验代码是否忠实实现 Plan；
- B 模式核对派生实现与原设计、CodeLineageRecord；
- 重新计算关键指标和统计量；
- 核对数据、seed、config、环境和代码 hash；
- 验证 Artifact 完整性和 provenance；
- 只报告问题，不修改原始证据。

### 12.5 Scientific Reviewer

- 评估模型、实现、实验和分析的整体科学质量；
- 检查替代解释、混杂变量和结论强度；
- 检查复用和修改是否影响科研结论；
- 判断是否需要补实验或修改 Plan；
- 判断是否具备进入正式 Research Review 的条件。

---

## 13. 通用实验执行

### 13.1 通用 API

移除专用入口 `POST /api/projects/{project_id}/experiments/weight-decay`，替换为：

```text
POST /api/projects/{project_id}/studies
GET  /api/projects/{project_id}/studies
GET  /api/projects/{project_id}/studies/{study_id}
POST /api/projects/{project_id}/studies/{study_id}/runs
GET  /api/projects/{project_id}/studies/{study_id}/runs
GET  /api/projects/{project_id}/runs/{run_id}
```

### 13.2 执行链

```text
Approved Plan
    ↓
Validated StudySpec
    ↓
Materialized immutable runner
    ↓
Deterministic local execution
    ↓
Immutable ExperimentRun
    ↓
Hash-addressed Artifacts
```

LLM 不得直接提交任意 shell、绕过 Plan 运行实验、动态安装依赖、修改已批准矩阵、删除失败 Run、覆盖历史 Artifact 或将 API key 传递给实验进程。

---

## 14. 独立科研评审 Multi-Agent

### 14.1 Meta Reviewer

分派独立评审、汇总 Reviewer 意见、处理矛盾并输出最终科研评审建议。它不参与原研究内容首次生成，不能绕过确定性 Policy Guard。

### 14.2 Methodology Reviewer

检查研究设计、baseline、控制变量、消融、实验与 Hypothesis 的对应关系、替代解释和外部有效性。

### 14.3 Statistical Reviewer

检查统计方法、样本量、效应量、不确定性、多重比较、异常值和失败 Run，并独立复核关键统计结论。

### 14.4 Evidence & Reproducibility Reviewer

检查结论与 EvidenceClaim 绑定，核对 Artifact、代码、配置、环境、Code Lineage、引用和 provenance，并判断研究能否复现。

Review 结果包括：

- `SUPPORTED`
- `NEGATIVE_RESULT`
- `INSUFFICIENT_EVIDENCE`
- `RETURN_TO_EXPERIMENT`
- `REVISE_PLAN`

最终 Workflow 决定由确定性 Policy Guard 执行。

---

## 15. 论文写作 Multi-Agent

### 15.1 Lead Author

确定核心贡献和完整 outline，维护统一叙事、术语、符号和结论边界，整合其他 Editor 内容，并根据 Reviewer 意见完成 revision。

### 15.2 Technical Content Editor

负责 Method、Theory、Experimental Setup、Results 和 Analysis，检查公式、算法、代码、实验配置、baseline、ablation、统计结果和复现细节的一致性。

### 15.3 Related Work & Citation Editor

负责 Introduction、Related Work 和 References，核对 novelty claim、DOI、版本、作者、引用位置和 BibTeX，禁止虚构和未验证引用。

### 15.4 Presentation & LaTeX Editor

负责 NeurIPS、ICML、ICLR 或通用顶会模板、LaTeX、表格、图片、算法、附录、页数、交叉引用、PDF 构建和视觉检查。B 模式优先继承已批准的 VisualizationProfile。不得修改实验原始数值。

### 15.5 Top-Conference Reviewer

按照目标会议标准检查 novelty、technical correctness、empirical rigor、significance、clarity、reproducibility、limitations 和 broader impact，输出 blocking、major、minor 缺陷和 submission readiness。

### 15.6 写作流程与配置

```text
Verified Evidence Pack
        ↓
Lead Author：贡献和 Outline
        ↓
Technical Content Editor ─────┐
Citation Editor ──────────────┤
        ↓                     │
Lead Author：统一整合 ←───────┘
        ↓
Presentation & LaTeX Editor
        ↓
Top-Conference Reviewer
        ↓
Lead Author Revision
        ↓
确定性引用、数字、LaTeX 和 PDF 检查
```

```yaml
paper:
  target_venue: neurips
  target_year: configurable
  max_review_rounds: 2
  max_parallel_agents: 2
  require_verified_citations: true
  require_claim_evidence_links: true
  output_formats:
    - latex
    - pdf
    - markdown
```

---

## 16. 论文输出与证据约束

输出包括 `paper.tex`、`references.bib`、figures、tables、appendix、reproducibility statement、build manifest、PDF、Markdown preview、claim-evidence index、citation verification report、paper review history 和 revision history。

默认论文结构：Abstract、Introduction、Related Work、Method、Experimental Setup、Results、Analysis and Discussion、Limitations、Broader Impact、Conclusion、References、Appendix 和 Reproducibility Statement。

所有主要数字必须绑定 Artifact，所有主要结论必须绑定 EvidenceClaim，所有引用必须绑定真实 LiteratureSource 和可验证定位。Abstract-only 来源不得支持核心结论。证据不足时必须降低结论强度。Writer 不得生成不存在的实验、引用或统计结果。

---

## 17. Agent 可审计性

每个 AgentRun 记录 role、stage、provider、model、prompt/template version、input context hash、output hash、token usage、duration、tool calls、parent run、accepted/rejected status、rejection reason 和 revision number。

不得记录 API key、authorization header、cookie、secret 或未脱敏凭据。被拒绝的 Agent 输出必须保留，不得覆盖。

---

## 18. 前端改造

新增：

1. Provider、模型和 API key 配置与连接测试；
2. Project Understanding 和 B 模式 Legacy Reuse Assessment；
3. 文献多查询过程和 Evidence Matrix；
4. Hypothesis 候选、复用策略和 Plan 审批；
5. Multi-Agent 活动、token、费用和预算；
6. Code Lineage、实现 diff 和语义修改标识；
7. 通用 Study、Run Matrix、日志、指标和 Artifact；
8. VisualizationProfile、FigureSpec 和 legacy/new figure 对比；
9. Verification、Scientific Review 和 Independent Research Review；
10. Paper outline、section revisions 和 Top-Conference Reviewer defects；
11. LaTeX/PDF 预览和下载；
12. 状态、事件、失败、暂停、恢复和取消控制。

前端不得提供任意 Python、shell 或解释器输入入口。

---

## 19. v0.1 兼容与迁移

- 不修改或覆盖 v0.1 runtime data。
- v0.2 使用独立数据库和 Artifact 根目录。
- 提供只读 v0.1 importer。
- 保留 weight-decay Study 为 `builtin/weight_decay_v1`。
- 原 ExperimentRun、Artifact、EvidenceClaim、负结果和失败记录可以复制到 v0.2 snapshot。
- 迁移后重新计算 manifest/hash，不修改原记录。
- 不执行 v0.1 或 legacy 项目代码。

---

## 20. 建议目录结构

```text
v_0_2/
├── apps/
│   ├── backend/
│   └── frontend/
├── research_runtime/
│   ├── agents/
│   │   ├── literature/
│   │   ├── research_design/
│   │   ├── experiment/
│   │   ├── review/
│   │   └── writing/
│   ├── llm/
│   │   ├── providers/
│   │   ├── registry.py
│   │   └── secrets.py
│   ├── literature/
│   ├── studies/
│   │   ├── registry.py
│   │   ├── models.py
│   │   └── builtin/
│   ├── experiments/
│   ├── analysis/
│   ├── evidence/
│   ├── review/
│   ├── writing/
│   ├── visualization/
│   ├── workflow/
│   └── workspace/
├── storage/
├── templates/
│   └── paper/
├── tests/
├── docs/
├── scripts/
└── plan.md
```

---

## 21. 开发里程碑

### Milestone 0：v0.2 骨架与边界

- 创建独立配置、数据库和 runtime root；
- 建立 Workflow、Job、Artifact 和安全边界；
- 建立测试骨架；
- 确认现有依赖，不安装新包。

### Milestone 1：LLM Provider

- Provider Registry 和 OpenAI-compatible Provider；
- API key 和模型配置；
- 连通性测试、redaction、usage、预算、错误和重试。

### Milestone 2：通用 Project Understanding 与 B 模式继承

- A/B 模式通用化并移除 weight-decay 默认值；
- 移除特定文件名假设；
- 建立 ResearchContext 和 LegacyReuseAssessment；
- 建立 CodeLineageRecord、VisualizationProfile 和 FigureSpec；
- 支持代码、配置、Notebook、PDF、已有实验和图片摘要。

### Milestone 3：文献研究 Multi-Agent

- Literature Lead 和 Evidence Reviewer；
- arXiv、OpenAlex、Crossref；
- 查询规划、去重、排序、全文读取、Evidence Matrix 和 Research Gap。

### Milestone 4：Hypothesis 与 Plan Multi-Agent

- Research Design Lead 和 Critical Reviewer；
- 多候选 Hypothesis；
- 通用 StudySpec；
- B 模式复用策略和补充实验；
- 用户审批、revision 和 provenance。

### Milestone 5：实验实现和通用执行

- Experimental Lead / Modeling Scientist；
- Research Engineer；
- B 模式代码复制、适配、diff 和血缘；
- 通用 Study Registry、Study/Run API 和 runner materialization；
- smoke、测试、Artifact、图片继承和失败恢复。

### Milestone 6：Analysis 与实验审核

- Statistical Analyst；
- 通用 MetricSpec 和 AnalysisSpec；
- Verification Auditor 和 Scientific Reviewer；
- 支持负结果和证据不足。

### Milestone 7：独立科研评审

- Meta Reviewer、Methodology Reviewer、Statistical Reviewer、Evidence & Reproducibility Reviewer；
- Policy Guard 和 Review feedback loops。

### Milestone 8：顶会风格 Writer

- Lead Author、Technical Content Editor、Related Work & Citation Editor、Presentation & LaTeX Editor、Top-Conference Reviewer；
- revision loop、LaTeX、BibTeX、PDF 和视觉 QA。

### Milestone 9：前端集成

- Provider 设置、Multi-Agent activity、Evidence Matrix、Legacy Reuse、Code Lineage、Visualization、Study、Review、Paper revision 和 PDF preview。

### Milestone 10：兼容与验收

- 导入 v0.1 weight-decay Study；
- 任意 Topic 和任意允许项目端到端验收；
- B 模式继承已有代码和图片风格验收；
- failure recovery、pause/resume/cancel；
- secret leakage、Artifact tamper、负结果和证据不足测试。

---

## 22. 测试策略

### 22.1 单元测试

- Provider structured output 和 secret redaction；
- AgentRoleRegistry；
- query planning 和 literature deduplication；
- StudySpec、RunSpec、MetricSpec 和 AnalysisSpec；
- Plan hash binding；
- Code Lineage 和修改分类；
- VisualizationProfile 和 FigureSpec；
- Claim–Evidence validation；
- Workflow transition。

### 22.2 集成测试

- Topic → Literature → Hypothesis；
- B 模式 import → Legacy Reuse → code adaptation → smoke；
- Hypothesis 和 Plan rejection/revision；
- Plan → implementation → Study → Runs → Artifacts；
- Experiment failure/recovery；
- Analysis → Verification → Research Review；
- Paper review/revision；
- API key connection and redaction。

### 22.3 安全测试

- 非 loopback host、越界 import、symlink escape、legacy direct execution、shell injection 和 Artifact path traversal 拒绝；
- API key 日志和实验环境泄漏检查；
- 未审批实验和 semantic patch 拒绝。

### 22.4 科研质量测试

- 引用存在且可定位；
- Abstract-only 不支持主要结论；
- 主要数字全部绑定 EvidenceClaim；
- 统计结果可以重新计算；
- Agent 生成代码与 Plan 一致；
- B 模式派生实现与 CodeLineage 一致；
- 新图片来自已验证 Artifact 并符合 VisualizationProfile；
- Reviewer 使用独立上下文；
- 负结果和失败记录完整保留；
- 证据不足不会被扩写成支持性结论；
- LaTeX 可构建且 PDF 通过视觉检查。

---

## 23. v0.2 验收标准

1. 任意非 weight-decay Topic 可以完成文献、假设和 Plan。
2. 任意允许目录中的项目可以只读导入并生成 ResearchContext。
3. B 模式能够识别、审批和执行 adapt、refactor 或 reimplementation 策略。
4. B 模式原目录保持只读，实际执行代码来自受控 Workspace 副本。
5. B 模式每项派生代码都有 CodeLineageRecord 和语义修改分类。
6. B 模式正式图片从新 Artifact 生成并继承已批准的 VisualizationProfile。
7. 用户能够配置真实 LLM Provider、模型和 API key。
8. API key 不出现在持久化记录、日志和实验环境中。
9. 文献阶段至少使用两个公共来源，并记录查询、失败、版本和引用定位。
10. Hypothesis 和 Plan 经过 Lead、Reviewer 和用户审批。
11. 实验由通用 StudySpec 驱动，不依赖 `weight_decay` 字段。
12. 实验代码经过 Research Engineer 实现和 Verification Auditor 核验。
13. 统计分析可以由确定性代码重新计算。
14. Research Review 使用独立 Reviewer Team。
15. Critic 根据 Plan 和 Evidence 检查任意研究指标。
16. Writer 能生成完整 LaTeX、BibTeX、图表、附录和 PDF。
17. 论文经过 Top-Conference Reviewer 和 revision。
18. 所有主要结论和数字具有可验证证据链接。
19. 负结果、失败结果和证据不足结果不会被删除或覆盖。
20. v0.1 weight-decay Study 可以作为内置回归案例运行或导入。
21. 全流程支持持久化、暂停、恢复、取消和幂等重试。
22. 所有 Python 命令在 Conda `d2l` 环境中执行。
23. 不经用户批准不安装、删除或升级依赖。

---

## 24. 实施优先级

### 第一优先级

- Provider Registry 和 API key 安全配置；
- 通用 Project Understanding；
- B 模式 Legacy Reuse、Code Lineage 和 Visualization Profile；
- 清除 weight-decay 主流程硬编码；
- 通用 StudySpec、RunSpec、MetricSpec 和 AnalysisSpec。

### 第二优先级

- Literature Multi-Agent；
- Hypothesis/Planning Multi-Agent；
- 通用实验执行；
- Experiment/Analysis Multi-Agent；
- Evidence Store。

### 第三优先级

- Independent Research Review；
- 顶会风格 Writer；
- LaTeX/PDF；
- 完整前端体验。

v0.2 应首先保证研究内容正确、证据可靠、旧项目继承准确、执行安全和过程可审计，再提升论文篇幅、视觉表现和 Agent 能力。
