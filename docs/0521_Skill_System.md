# 2024-05-21 — Skill 可插拔知识模块系统

## 动机

Agent 需要一个可扩展的知识注入机制：在不修改 prompt 模板或工具代码的前提下，
通过文件系统添加领域知识、工作流指引。Skill 就是这个机制。

## 设计

### 文件结构

```
agent/skills/
├── sample/
│   └── Skill.md          ← # Title + 描述段 + 详细指引
├── git_commit_skill/
│   └── Skill.md
└── <future_skill>/
    └── Skill.md
```

每个 Skill 是一个目录，内含唯一的 `Skill.md`。目录名即技能名。

### 数据流

```
skills/*/Skill.md
  │
  ├─ scan_skills()          → 启动时扫描，提取标题+首段摘要
  │     └─ get_skills_summary()  → 注入 system prompt
  │
  └─ LoadSkill.execute()    → LLM 按需加载完整 Markdown
        └─ get_skill(name).full_content()
```

### System Prompt 注入

```
## Available tools
...
- Shell / Read / Write / Edit / Search / LoadSkill — executable tools

## Available skills (use LoadSkill to get full details):
  - git_commit_skill: A Git specialist for making safe commits...
  - sample: A demonstration skill that shows how Skills work...
```

### LoadSkill 工具

```json
{"kind": "LoadSkill", "name": "git_commit_skill"}
```

返回 `Skill.md` 完整内容。

## 新增文件

| 文件 | 说明 |
|------|------|
| `agent/tools/skill.py` | 技能扫描器 + `SkillInfo` 数据结构 + `LoadSkill` 工具 |
| `agent/skills/sample/Skill.md` | 示例技能 |

## 修改文件

| 文件 | 变更 |
|------|------|
| `agent/tools/__init__.py` | +`LoadSkill` 到 `_ALL_TOOL_CLASSES` 和 `__all__` |
| `agent/react.py` | system prompt 新增 `{skills_summary}` 占位符 |

## 验证

```bash
# 扫描技能
uv run python -c "from agent.tools.skill import scan_skills; print(scan_skills())"

# Agent 查询可用技能
curl -X POST localhost:8000/api/agent/stream \
  -d '{"question":"what skills are available?","max_steps":5}'
# → "The available skills are: 1. git_commit_skill ... 2. sample ..."
```

## 扩展

新增 Skill 只需：
1. 在 `agent/skills/` 下创建 `<name>/Skill.md`
2. 无需修改任何代码，重启后自动生效
