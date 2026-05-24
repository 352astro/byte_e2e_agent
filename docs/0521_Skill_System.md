# 2026-05-21 — Skill 特化能力模块

## 动机

这个项目不需要复杂插件平台，但需要清晰表达特化能力。Skill 用 Markdown 描述某个
可复用能力的适用场景、执行流程和约束，让 Agent 在需要时按名字加载完整内容。

## 设计

### 文件结构

```
agent/skills/
├── git_commit_skill/
│   └── Skill.md
└── <future_skill>/
    └── Skill.md
```

每个 Skill 是一个目录，内含唯一的 `Skill.md`。目录名即技能名。

`Skill.md` 推荐格式：

```markdown
# Human Readable Skill Name

One short paragraph describing when this skill is useful.

## Instructions

1. Do the first thing.
2. Do the next thing.
```

### 数据流

```
skills/*/Skill.md
  │
  ├─ scan_skills()          → 扫描目录，提取首段摘要
  │     └─ skill_context_message()  → 生成独立系统消息
  │
  └─ LoadSkill.execute()    → LLM 按需加载完整 Skill 内容
        └─ get_skill(name).read()
```

### 独立 Skill 上下文与热重载

```
system prompt
skill context system message
task context user message
conversation history
```

Skill 不放进主 system prompt。`ReActAgent` 每次调用模型前都会像加载 task context 一样
重新生成一条独立的 system 消息：

```text
## Available Skills
Skills are specialized capability modules.
This list is reloaded before each model step.
When a skill matches the task, call LoadSkill with its name, read the full Skill content, then continue with normal tools.

- git_commit_skill: Use this skill when the user asks the agent to make a small...
```

因此已有会话也能看到 `Skill.md` 的新增、删除和修改。

### LoadSkill 工具

```json
{"name": "git_commit_skill"}
```

返回 `Skill.md` 完整内容。

## 相关文件

| 文件 | 变更 |
|------|------|
| `agent/tools/skill.py` | 扫描 Skill、生成摘要、实现 `LoadSkill` |
| `agent/tools/__init__.py` | 注册 `LoadSkill` |
| `agent/react.py` | 每个模型 step 单独加载 Skill context 和 Task context |
| `agent/skills/<name>/Skill.md` | 具体 Skill 内容 |

## 验证

```bash
# 扫描技能
uv run python -c "from agent.tools.skill import scan_skills; print(scan_skills())"

# Agent 查询可用技能
curl -X POST localhost:8000/api/agent/stream \
  -d '{"question":"what skills are available?","max_steps":5}'
# → "## Available Skills ... git_commit_skill ..."
```

## 扩展

新增 Skill 只需：
1. 在 `agent/skills/` 下创建 `<name>/Skill.md`
2. 无需修改任何代码，下一次模型 step 会重新扫描并注入

刻意不做：manifest、版本、权限、依赖、触发器。当前目标是让特化 agent 的行为更清楚，
而不是维护一个通用插件生态。
