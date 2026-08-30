# AutoResearch v0.2 项目执行步骤与用户流程

## 1. 总体闭环

AutoResearch 的整体流程是：

```text
项目入口
  → 项目理解
  → 文献证据
  → 研究设计
  → 实验实现
  → Smoke Run
  → Formal Run
  → 确定性分析
  → Verification / Scientific Review
  → Independent Research Review
  → 论文写作与审查
  → 完成
```

系统通过前端控制台、loopback API、SQLite 持久化、LLM Agent、确定性分析器和受限实验运行时协作完成整个流程。

## 2. 用户使用流程

### 2.1 启动系统

后端 API 监听 `127.0.0.1:8100`，前端控制台监听 `127.0.0.1:3000`。

前端加载后，会从后端恢复：

- 项目列表和当前状态；
- 研究阶段记录；
- 事件和 Durable Job；
- 文献、实验、分析、评审和论文 Artifact。

页面不依赖 localStorage、sessionStorage 或浏览器端 API Key 持久化。页面会定期轮询事件和项目快照，以支持刷新和服务重启后的恢复。

### 2.2 配置模型

进入“模型配置”后可以：

- 配置默认 Provider、模型、Base URL 和协议；
- 为项目理解、文献、研究设计、实验代码、分析、科研评审和论文写作配置阶段模型；
- 设置调用次数、Token、成本、超时和重试预算；
- 提交 API Key；
- 运行连接测试。

API Key 只保存在后端进程内存中，提交后前端输入框会清空。

### 2.3 新建项目

点击“新建研究”，选择以下入口之一：

- A 模式：从新的研究问题开始；
- B 模式：从已有项目开始。

填写项目名称、研究目标和可选的补充约束。B 模式还需要填写已有项目目录，该目录必须位于后端配置的 `allowed_import_roots` 内。

提交后系统会自动：

1. 创建项目记录；
2. B 模式下创建已有项目的只读导入快照；
3. 执行 Project Understanding；
4. 将项目状态推进到 Literature。

## 3. 科研阶段

| 阶段 | 系统执行 | 用户操作 |
|---|---|---|
| 项目理解 | 解析研究目标；B 模式静态扫描代码、Notebook、配置、旧结果和图片 | 检查研究目标和理解结果 |
| 文献证据 | 多 Agent 检索、核实来源、构建证据矩阵和研究缺口 | 设置是否允许网络，然后运行文献检索 |
| 研究设计 | 生成多个 Hypothesis 候选，并由 Critical Reviewer 检查 | 选择候选，批准或退回修改 |
| 实验计划 | 生成实验条件、对照、指标、预算和 RunSpec | 批准或退回实验计划 |
| 实验实现 | Experimental Lead 生成任务图，Research Engineer 生成代码，静态验证代码 | 查看实现 Diff 和 Code Lineage |
| Smoke Run | 针对每个 RunSpec 执行小规模测试 | 点击 Smoke，确认运行成功 |
| Formal Run | Smoke 成功后执行正式实验 | 点击 Formal |
| 分析 | 根据批准的 AnalysisSpec 进行确定性统计分析，生成 JSON、CSV 和 SVG | 查看指标、比较结果、图表和 Artifact |
| Verification | 重新验证代码、配置、环境、Artifact 哈希和统计结果 | 查看验证结果 |
| Scientific Review | 审核结论强度，判断是否可以进入正式 Research Review | 查看审核建议 |
| Research Review | 3 个隔离专家、Meta Reviewer 和 Policy Guard 形成最终决策 | 应用精确评审决策 |
| 论文 | Lead Author、Technical Editor、Citation Editor、Presentation Editor 和顶会 Reviewer 协作 | 选择目标会议，查看论文和修订结果 |
| 完成 | 执行 LaTeX 构建、PDF 生成、逐页视觉检查和质量门禁 | 下载 PDF、Markdown、LaTeX 等产物 |

## 4. 状态机与反馈循环

主状态机如下：

```text
INITIALIZING
  → PROJECT_UNDERSTANDING
  → LITERATURE
  → HYPOTHESIS
  → WAIT_HYPOTHESIS_APPROVAL
  → EXPERIMENT_PLANNING
  → WAIT_PLAN_APPROVAL
  → EXPERIMENT_IMPLEMENTATION
  → EXPERIMENT
  → ANALYSIS
  → RESEARCH_REVIEW
  → REPORT_PLANNING
  → REPORT_WRITING
  → REPORT_REVIEW
  → COMPLETED
```

允许的反馈循环：

- Hypothesis 被拒绝：返回 `HYPOTHESIS`；
- Experiment Plan 被拒绝：返回 `EXPERIMENT_PLANNING`；
- 实现发现需要改变实验语义：返回 `EXPERIMENT_PLANNING`，创建新的 Plan revision；
- Analysis 发现批准范围内实验缺失：返回 `EXPERIMENT`；
- Research Review 发现方法问题：返回 `EXPERIMENT_PLANNING`；
- Research Review 发现实验缺失：返回 `EXPERIMENT`；
- Report Review 发现写作问题：返回 `REPORT_WRITING`；
- Report Review 发现证据问题：返回 `RESEARCH_REVIEW`、`EXPERIMENT` 或 `EXPERIMENT_PLANNING`。

新增实验、改变指标、扩大预算、修改实验语义或增加依赖时，必须创建新的 Plan revision 并重新审批。

## 5. A/B 模式差异

### A 模式：从 Topic 开始

```text
用户 Topic 与约束
  → Project Understanding
  → Literature Multi-Agent
  → Hypothesis & Planning Multi-Agent
  → 用户审批
  → 实验实现、执行、分析与评审
  → 论文写作与审查
```

A 模式不预设 weight decay、网络结构、数据集、指标或实验方法。研究内容必须来自用户 Topic、检索证据、用户约束和已批准的研究设计。

### B 模式：继承已有项目

```text
已有项目只读快照
  → Project Understanding
  → 解析代码、实验、结果和图片设计
  → Legacy Reuse Assessment
  → 直接适配 / 局部重构 / 安全重实现
  → Literature、Hypothesis 与 Planning
  → 用户审批复用范围和补充实验
  → 复制候选代码到 v0.2 Workspace
  → Research Engineer 适配副本
  → Verification Auditor 核对语义和血缘
  → Smoke Test
  → Deterministic Experiment Runtime
  → 按已有视觉规范生成新图片并补充分析
```

B 模式不会直接运行原始项目代码。原始代码只作为只读数据进行解析，执行时使用经过审批并复制到 v0.2 Workspace 的派生代码。

## 6. 实验运行规则

实验只能通过已持久化的 Study 和 RunSpec 启动，前端没有任意 Shell、Python 或命令执行入口。

每个正式实验通常遵循：

```text
创建 Study
  → 每个 RunSpec 执行 Smoke
  → Smoke 成功
  → 执行 Formal Run
  → 注册并哈希校验 Artifact
  → 确定性分析
```

Run 可以处于 queued、running、paused、completed、failed、stale、cancelled 等状态。

- Pause：请求暂停当前运行；
- Cancel：取消当前运行；
- Resume：为失败、暂停或中断的运行创建新的子 attempt；
- 原始 Run 记录和失败记录始终保留；
- Smoke Run 不具备正式证据资格；
- 只有成功完成的 Formal Run 才可以进入正式证据包。

实验子进程使用固定参数、受限工作目录和 `d2l` 环境，禁止网络、额外进程创建和越界写文件。

## 7. 分析、评审与论文

### 7.1 分析

确定性 Statistical Analyst 只读取批准的 AnalysisSpec 和已验证 Artifact，不能由 LLM 直接修改数字。

分析会保留：

- 分析 JSON；
- 结果 CSV；
- 结果 SVG；
- 输入 Artifact ID 和哈希；
- supported、negative_result 或 insufficient_evidence 等结果边界。

### 7.2 Research Review

正式 Research Review 包含：

1. Methodology Reviewer；
2. Statistical Reviewer；
3. Evidence & Reproducibility Reviewer；
4. Meta Reviewer；
5. Deterministic Policy Guard。

三个专家分别使用隔离上下文，Meta Reviewer 只接收已完成的专家报告。最终决策由 Policy Guard 结合证据、哈希、统计结果和审批状态确定，不能由 Reviewer 文字直接覆盖。

最终决策可能是：

- `supported`；
- `negative_result`；
- `insufficient_evidence`；
- `return_to_experiment`；
- `revise_plan`。

### 7.3 论文

只有应用合格的 Research Review 决策后，才进入论文流程。

论文流程包括：

1. 生成论文计划；
2. Lead Author 组织论文结构和主要叙事；
3. Technical Editor 编写方法、实验和结果；
4. Citation Editor 绑定文献来源、证据和引用；
5. Presentation Editor 处理图、表、附录和 LaTeX；
6. Top-Conference Reviewer 独立评审；
7. 最多两轮 revision；
8. 执行 LaTeX 构建和 PDF 逐页视觉 QA；
9. 通过 claim、number、citation、visualization 和 reproducibility 门禁后完成。

负结果和证据不足也可以进入论文，但论文必须明确报告其边界，不能被文字扩写成肯定性结论。

## 8. 当前项目状态

当前项目：`Weight Decay Minimal End-to-End Validation`

当前持久化状态：

- 模式：A / Topic；
- 当前阶段：`Experiment`；
- 状态：`Active`；
- 文献来源：60；
- 证据条目：31；
- 实验运行：7；
- 分析结果：2；
- Research Review：1；
- 论文：0；
- 研究结论：尚未确定。

当前运行记录包括：

- 3 次失败的 Smoke attempt；
- 2 次成功的 Smoke Run；
- 2 次成功的 Formal Run，分别对应两个实验条件，形成 1 对正式观测。

最新分析结果为 `insufficient_evidence`。最新 Research Review 决策为 `return_to_experiment`，但尚未应用。

## 9. 当前实现中的流程断点

设计上，完成实验后应该继续：

```text
EXPERIMENT
  → ANALYSIS
  → RESEARCH_REVIEW
  → REPORT_PLANNING
  → REPORT_WRITING
  → COMPLETED
```

当前后端的 `reconcile_workflow` 只会自动推进到 `EXPERIMENT_IMPLEMENTATION`，不会自动触发：

- `EXPERIMENT → ANALYSIS`；
- `ANALYSIS → RESEARCH_REVIEW`。

因此当前页面虽然已经有 Analysis 和 Research Review 记录，项目状态仍然停留在 `Experiment`。

同时，应用 Research Review 决策的接口要求项目当前处于 `RESEARCH_REVIEW`，因此当前“应用精确评审决策”按钮可能会被后端拒绝；论文按钮也无法正常进入写作阶段。

本项目的评审还指出，当前只有 1 对正式观测，统计上不足以完成需要至少 2 对完整观测的配对分析。由于现有 RunSpec 已有正式 attempt，不能简单重复点击 Formal；如果继续补实验，应通过新的 Plan revision 增加重复实验并重新审批。

## 10. 主要实现位置

- 状态机：[research_runtime/workflow/transitions.py](../research_runtime/workflow/transitions.py)
- 工作流协调：[apps/backend/main.py](../apps/backend/main.py)
- 前端主控制台：[apps/frontend/components/research-console.tsx](../apps/frontend/components/research-console.tsx)
- 项目创建：[apps/frontend/components/project-create.tsx](../apps/frontend/components/project-create.tsx)
- 项目工作区：[apps/frontend/components/project-workbench.tsx](../apps/frontend/components/project-workbench.tsx)
- 前端 API 边界：[apps/frontend/lib/api.ts](../apps/frontend/lib/api.ts)
- 实验运行服务：[research_runtime/experiments/service.py](../research_runtime/experiments/service.py)
- 分析与科研评审：[research_runtime/analysis/service.py](../research_runtime/analysis/service.py)
- 独立 Research Review：[research_runtime/review/service.py](../research_runtime/review/service.py)
- 论文写作：[research_runtime/writing/service.py](../research_runtime/writing/service.py)
