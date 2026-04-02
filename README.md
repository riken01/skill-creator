# Skill Creator — OpenClaw 适配说明

本文件记录了 OpenClaw 版 skill-creator 相对于上游版本（`skill-creator-for-claw`）所做的适配修改。

---

## 适配背景

上游版本面向 Claude Code CLI、Claude.ai、Cowork 等多平台，包含浏览器可视化反馈系统。OpenClaw 版针对 OpenClaw 运行环境进行了裁剪和优化。

---

## 主要变更

### 1. 结构精简

- 篇幅从 486 行压缩至约 215 行（减少 ~55%）
- 去除对话式、鼓励性语言，改为命令式步骤编号
- 顶部新增 **Common failure modes** 强制检查点块，明确列出三类常见跳步错误

### 2. Eval 流程重构

上游版本围绕浏览器可视化 reviewer 构建反馈循环：

```
并行启动 with-skill + baseline → eval-viewer/generate_review.py → 用户在浏览器中评审 → 下载 feedback.json
```

OpenClaw 版移除了整个浏览器 viewer 子系统，改为线性流程：

```
顺序运行 with-skill + baseline → grader subagent → aggregate script → analyst pass → 对话中呈现结果
```
### 3. Description Optimization 简化

| 项目 | 上游版本 | OpenClaw 版本 |
|------|----------|---------------|
| eval query 数量 | 20 个 | 12 个（6 should-trigger + 6 should-not-trigger） |
| 用户评审方式 | `assets/eval_review.html` 模板 + 浏览器下载 JSON | 直接 JSON，细节委托给 `references/description-optimization.md` |
| HTML 模板步骤 | 有 | 移除 |

### 4. 平台 section 替换

| 上游版本 | OpenClaw 版本 |
|----------|---------------|
| `Claude.ai-specific instructions` | 移除 |
| `Cowork-Specific Instructions` | 移除 |
| 无 | 新增 `OpenClaw-Specific Notes` |

`OpenClaw-Specific Notes` 说明：
- 技能从 `~/.openclaw/workspace/skills/` 加载，新安装的技能在下一个对话 turn 生效
- 临时技能注入路径为 `~/.openclaw/workspace/skills/<unique-name>/`，由 `run_eval.py` 自动清理
- Description optimization 为每个 query 创建独立 agent 以实现 session isolation，由 `run_eval.py` 处理，无需手动管理
- 更新现有技能时保留原目录名和 `name` frontmatter；如安装路径只读，先复制到 `/tmp/skill-name/` 再编辑

### 5. 写作风格

移除所有鼓励性、情感化表达（例如上游版本中的 _"This task is pretty important (we are trying to create billions a year in economic value here!)"_），保留纯指令内容。

### 6. `run_eval.py` / `improve_description.py` CLI 适配

上游版本通过 `claude -p` 启动一次性 Claude Code 子进程来运行每个 query。OpenClaw 版做了两项关键改动：

**① 测试 Agent（`description-improvement`）**

不再每次启动一个全新进程，而是复用一个专用 agent：

```python
EVAL_AGENT_NAME = "description-improvement"
```

`ensure_eval_agent()`（`scripts/utils.py`）在首次运行时自动创建该 agent（`openclaw agents add description-improvement --workspace ~/.openclaw/workspace-description-improvement`），后续直接复用。每个 query 使用 `/new` 前缀开启新会话以保持上下文隔离：

```python
cmd = ["openclaw", "agent", "--agent", agent_name, "--local", "--message", f"/new {query}"]
```

**日志检查触发判定**

上游版本通过 `claude -p` 的 stdout 解析是否触发了 skill。OpenClaw 版改为检查 agent 的 session 日志文件，查找 `read` 工具调用中是否包含临时 skill 的路径：

```
~/.openclaw/agents/description-improvement/sessions/*.jsonl
```

日志中工具调用格式为：
```json
{"type": "toolCall", "name": "read", "arguments": {"path": "..."}}
```

`_check_new_lines_for_skill_read()` 扫描最新 session log，匹配 `skill_path_fragment`，有则判定为已触发。每次 query 结束后，新产生的 session log 会被自动清理以节省磁盘。

---

## 未变更部分

- YAML frontmatter（`name`、`description`）完全一致
- `agents/`、`scripts/`、`references/` 目录结构不变
- `package_skill.py` 打包流程逻辑不变
- Blind comparison（`agents/comparator.md`）保留为可选高级功能
- `run_loop.py` 描述优化脚本用法基本一致
