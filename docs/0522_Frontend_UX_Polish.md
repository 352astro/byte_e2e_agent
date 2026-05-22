# 2026-05-22 — 前端 UX 打磨

## 变更

### 1. 最新气泡默认展开

`finish` 事件不再调用 `finalizeStep()`，最后一步保持 `open: true`。
用户可直接阅读最新推理结果，不必手动展开。

最新步的 Thinking 也默认展开（`<details open={isLatest}>`），旧步默认折叠。

### 2. 输入框固定底部

布局改为 `flex` 列：上方 `agent-scroll`（`flex: 1; overflow-y: auto`）+ 下方 `agent-input-bar`（`flex-shrink: 0`）。
输入栏始终固定在视口底部，不参与内容滚动。

### 3. 移除 Hello World

`App.jsx` 从 30 行精简为 6 行，不再显示 Hello World 标语和 `/api/hello` 状态检测。
页面直接渲染 `AgentDemo`。

### 4. 多行输入 + 快捷键

- `<input>` → `<textarea>`（支持多行）
- `Enter` 单独发送
- `Ctrl+Enter` / `Meta+Enter`（macOS）/ `Shift+Enter` 插入换行
- 行数自适应：1 行起步，最多 10 行后内部滚动

```jsx
const handleChange = (e) => {
  setQuestion(e.target.value);
  const lines = e.target.value.split("\n").length;
  e.target.rows = Math.min(Math.max(lines, 1), MAX_ROWS);
};
```

### 5. macOS 输入法 Enter 误触修复

`onCompositionStart` / `onCompositionEnd` 事件跟踪 IME 组合状态。
当 `composingRef.current === true` 时，Enter 键仅用于确认组合输入，不触发发送。

```jsx
const composingRef = useRef(false);

const onKeyDown = (e) => {
  if (e.key === "Enter") {
    if (e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (composingRef.current) return;
    e.preventDefault();
    handleRun();
  }
};
```

### 6. 命名统一

| 旧 | 新 |
|------|-----|
| `💜 Deep Think` | `💜 Thinking` |
| `💭 Thought` | `⚡ Action` |
| `step.thought` | `step.action` |
| `thoughtRef` / `thoughtFinal` | `actionRef` / `actionFinal` |

### 7. 组件抽象

AgentDemo 中的内联渲染逻辑提取为独立组件，便于后续为不同工具写特化渲染器。

```
AgentDemo.jsx          ← 布局 + 输入栏
  └─ StepCard.jsx      ← 单步卡片（Thinking + Action + 工具事件）
       └─ ToolRenderers.jsx  ← 按事件类型分发渲染
            ├─ terminal_stream  → 深色终端块（Shell 特化）
            ├─ tool_call        → 蓝色标签 + 参数 JSON
            ├─ tool_result      → 绿色输出 + 截断展开
            ├─ plan_*           → 紫色摘要
            ├─ subtask_*        → 青色摘要
            └─ error            → 红色警告
```

新增工具特化只需在 `ToolRenderers.jsx` 加一个 `if` 分支。

## 影响文件

| 文件 | 变更 |
|------|------|
| `src/App.jsx` | 移除 Hello World，直接渲染 AgentDemo |
| `src/App.css` | 精简为仅 font-family |
| `src/components/AgentDemo.jsx` | textarea + IME + 新布局 → 委托 StepCard |
| `src/components/AgentDemo.css` | 全高度 flex 布局 + textarea 样式 |
| `src/components/StepCard.jsx` | **新增** — 单步卡片抽象 |
| `src/components/ToolRenderers.jsx` | **新增** — 按事件类型分发渲染 |
| `src/hooks/useAgentStream.js` | finish 不折叠最后一步；thought → action 重命名 |

### 9. 流式 tool_call 进度 & Response 重命名

后端在工具调用累积过程中 yield `tool_call_stream` 事件，
前端实时渲染 `⏳ Shell …writing 234 tokens` 进度指示器。

"Action" 块重命名为 "Response"，改为纯文本展示（原名误导——这是 LLM 的文本回复，不是工具动作）。

| 文件 | 变更 |
|------|------|
| `backend/agent/react.py` | 新增 `tool_call_stream` 事件 yield |
| `src/hooks/useAgentStream.js` | 处理 `tool_call_stream` → 累积为 `tool_stream` |
| `src/components/StepCard.jsx` | "Action" → "Response"，纯文本展示 |
| `src/components/ToolRenderers.jsx` | 新增 `tool_stream` 进度渲染 |
| `src/components/AgentDemo.css` | 新增 `.response-*` `.tool-stream` 样式 |

### 8. Shell 工具调用风格化

Shell 的 `tool_call` 从朴素 JSON 渲染改为类代码块 + timeout 角标。

```
旧:  {"command": "ls -la", "timeout_ms": 10000}
新:  🔧 Shell  [10s]
     ┌─────────────────────────┐
     │ ls -la                  │  ← 深色等宽代码块
     └─────────────────────────┘
```

| 文件 | 变更 |
|------|------|
| `src/components/ToolRenderers.jsx` | Shell 分支：命令用 `.shell-command` 渲染，timeout 用 `.shell-timeout-badge` 角标 |
| `src/components/AgentDemo.css` | 新增 `.shell-call` `.shell-command` `.shell-timeout-badge` 样式 |
 