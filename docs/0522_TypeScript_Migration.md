# 2026-05-22 — 前端 TypeScript 迁移

## 动机

前端此前全部使用 JavaScript（`.jsx` / `.js`），缺乏编译期类型检查。SSE 事件分发、ToolEvent 渲染、状态管理等关键路径完全依赖运行时正确性。

迁移到 TypeScript 后，所有事件类型、组件 Props、Hook 返回值均受类型系统约束，拼写错误、字段缺失等问题在编译期即可发现。

## 变更

### 新增文件

| 文件 | 说明 |
|------|------|
| `frontend/tsconfig.json` | TypeScript 编译配置（strict 模式） |
| `frontend/src/types.ts` | 共享类型定义：`SSEEvent`（14 种变体的 discriminated union）、`ToolEvent`（9 种变体）、`Step`、`Message`、`SessionCache` |
| `frontend/src/vite-env.d.ts` | Vite 客户端类型声明（`.css` 导入等） |

### 转换文件

| 旧 (.js/.jsx) | 新 (.ts/.tsx) | 主要类型工作 |
|---------------|---------------|-------------|
| `src/main.jsx` | `src/main.tsx` | `getElementById(...)!` 非空断言 |
| `src/App.jsx` | `src/App.tsx` | `useState<string \| null>`、`SessionCache` 类型标注 |
| `src/hooks/useAgentStream.js` | `src/hooks/useAgentStream.ts` | 全部重构：`UseAgentStreamOptions`、`UseAgentStreamReturn` 接口；`dispatch(event: SSEEvent)` 带类型收窄的 switch；`HistoryTurn` / `HistoryToolCall` 接口 |
| `src/components/AgentDemo.jsx` | `src/components/AgentDemo.tsx` | `AgentDemoProps` 接口；`Item = ItemUser \| ItemStep` 联合类型；事件处理类型标注 |
| `src/components/StepCard.jsx` | `src/components/StepCard.tsx` | `StepCardProps` 接口 |
| `src/components/ToolRenderers.jsx` | `src/components/ToolRenderers.tsx` | `renderToolEvent(ev: ToolEvent, ...): ReactNode` 带类型收窄 |
| `src/components/SessionSidebar.jsx` | `src/components/SessionSidebar.tsx` | `SessionSidebarProps` 接口 |
| `src/components/Markdown.jsx` | `src/components/Markdown.tsx` | `MarkdownProps` 接口 |
| `vite.config.js` | `vite.config.ts` | 无逻辑变化 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `frontend/index.html` | `<script src="/src/main.jsx">` → `src="/src/main.tsx"` |
| `frontend/package.json` | 新增 `devDependency: typescript` |

### 删除文件

9 个旧 `.js` / `.jsx` 文件全部删除。

## 类型架构

```
src/types.ts  ←── 所有组件和 Hook 共享
  ├── SSEEvent    (14 种 SSE 事件的 discriminated union)
  ├── ToolEvent    (9 种前端渲染事件的 discriminated union)
  ├── Step         (单步推理卡片)
  ├── Message      (用户/助手消息气泡)
  └── SessionCache (会话级缓存)
```

## 构建验证

```bash
$ npx tsc --noEmit   # 零错误
$ npm run build      # 成功，25 modules transformed
```

## 未修改

- `backend/` 目录 — 零改动
- 所有 `.css` 文件 — 零改动
- 运行时行为 — 与 JS 版本完全等价，仅增加编译期类型检查
