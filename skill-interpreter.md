# Claude Code Skills 模块源码分析
## 代码结构
```
src/
├── skills/
│   ├── bundled/ 
│   ├── bundledSkills.ts
│   ├── loadSkillsDir.ts
│   └── mcpSkillBuilders.ts
└── tools/
    └── SkillTool/
```
---
## Overview
### What is a skill?
有两类skills，系统内置skills（BundledSkill）与从文件里读的skills。这两类skills被统一构造成Command，供LLM调用。
#### Bundled Skill
系统内置skills，代码在```skills/bundled```文件夹下，在bundledSkills.ts里面构造成Command。系统内置skill的数据结构如下：
```
export type BundledSkillDefinition = {
  name: string
  description: string
  aliases?: string[]
  whenToUse?: string
  argumentHint?: string
  allowedTools?: string[]
  model?: string
  disableModelInvocation?: boolean
  userInvocable?: boolean
  isEnabled?: () => boolean
  hooks?: HooksSettings
  context?: 'inline' | 'fork'
  agent?: string
  files?: Record<string, string>
  getPromptForCommand: (
    args: string,
    context: ToolUseContext,
  ) => Promise<ContentBlockParam[]>
}
```
这些系统内置技能在程序启动时注册，被存进bundledSkills。
#### 从文件读取的skill
从文件读取的skills是我们熟悉的skills，以SKILL.md的形式存在：
```
---
name: mcp-builder
description: Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when building MCP servers to integrate external APIs or services, whether in Python (FastMCP) or Node/TypeScript (MCP SDK).
license: Complete terms in LICENSE.txt
---

# MCP Server Development Guide

## Overview

Create MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. The quality of an MCP server is measured by how well it enables LLMs to accomplish real-world tasks.

---

# Process
...
```
通过loadSkillDir.ts构造成Command。
### 加载与激活skill
加载 = 把 skill 的定义（文件 / 插件 / 内置）转换成统一的 Command 对象，放进内存里供模型使用
激活 = 被纳入模型当前可见的 skill 列表
```
type Command = {
  name: string
  description: string

  // 类型（决定怎么执行）
  type: 'prompt' | 'local' | 'local-jsx'

  // 执行逻辑（prompt类）
  getPromptForCommand?: (args, context) => Promise<Prompt>

  // 来源
  source: 'builtin' | 'skills' | 'plugin' | 'bundled' | 'mcp'

  // 控制模型是否能调用
  disableModelInvocation?: boolean

  // 给模型看的触发提示（非常关键）
  whenToUse?: string
}
```
1. 启动时，使用getSkillDirCommands(cwd): 加载skills的总入口，它做了：
   - 从多个来源加载，包括用户目录(~/.claude/skills)、项目目录(项目目录向上找 .claude/skills)、policy(.claude/skills)、CLI参数--add-dir、旧commands(/commands/)
   - 读取SKILL.md，构造统一结构的Command
   - 去重
   - 分成两类，conditional和unconditional(根据skill.paths)，其中unconditional skills直接激活，而conditional skills存起来，只有path条件符合的时候才激活。
2. 运行时，当用户读/写/改某个文件，获取当前filePaths，使用discoverSkillDirsForPaths(filePaths)动态发现skills目录进行加载，activateConditionalSkillsForPaths(filePaths)条件激活skills。
#### SKILL.md的解析
SKILL.md 解析 = frontmatter（元数据） + markdown（prompt模板） → Command对象

首先把SKILL.md拆成元数据和body，元数据形如：
```
---
name: commit
description: Create a git commit
whenToUse: Use when saving changes
---
```
而其余部分作为body，最终被映射成:
```
const command: Command = {
  name,
  description,
  whenToUse,
  type: "prompt",
  source: "skills",

  async getPromptForCommand(args, context) {
    return [
      {
        type: "text",
        text: body
      }
    ]
  }
}
```

### 选择skill
1. skills激活后，进入动态的可用skill列表getDynamicSkills()，会参与模型选择。
### 使用skill
1. 如果匹配，通过getPromptForCommand(...)获取该skill对应的prompt，注入prompt。