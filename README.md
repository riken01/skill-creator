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

### 3. 字段名变更

| 文件 | 上游字段 | OpenClaw 字段 |
|------|----------|---------------|
| `eval_metadata.json` | `assertions` | `expectations` |

### 4. Description Optimization 简化

| 项目 | 上游版本 | OpenClaw 版本 |
|------|----------|---------------|
| eval query 数量 | 20 个 | 12 个（6 should-trigger + 6 should-not-trigger） |
| 用户评审方式 | `assets/eval_review.html` 模板 + 浏览器下载 JSON | 直接 JSON，细节委托给 `references/description-optimization.md` |
| HTML 模板步骤 | 有 | 移除 |

### 5. 路径硬编码

aggregate 脚本命令指定了 OpenClaw 绝对路径：

```bash
cd ~/.openclaw/workspace/skills/skill-creator && python3 -m scripts.aggregate_benchmark
```

上游版本为相对调用：`python -m scripts.aggregate_benchmark`。

### 6. 平台 section 替换

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

### 7. 写作风格

移除所有鼓励性、情感化表达（例如上游版本中的 _"This task is pretty important (we are trying to create billions a year in economic value here!)"_），保留纯指令内容。

---

## 未变更部分

- YAML frontmatter（`name`、`description`）完全一致
- `agents/`、`scripts/`、`references/` 目录结构不变
- `package_skill.py` 打包流程逻辑不变
- Blind comparison（`agents/comparator.md`）保留为可选高级功能
- `run_loop.py` 描述优化脚本用法基本一致
