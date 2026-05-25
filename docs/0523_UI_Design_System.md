# UI Design System — Monochrome Agent Interface

> **生效日期**：2026-05-23（最后修订：2026-06）
> **适用范围**：`frontend/` 下所有组件与样式
> **原则**：黑白灰主色调 + 语义色彩克制使用 + 融入式布局

---

## 1. 色彩体系

### 1.1 主色板（Monochrome）

| Token | 色值 | 用途 |
|---|---|---|
| `bg-page` | `#fff` | 页面底色、主内容区背景 |
| `bg-sidebar` | `#fafafa` | 侧边栏背景 |
| `bg-subtle` | `#f9f9f9` | thinking 完成态背景 |
| `bg-user` | `#f3f3f3` | 用户气泡背景 |
| `bg-hover` | `#eee` / `#e0e0e0` | 列表项、按钮 hover |
| `bg-active` | `#e8e8e8` | 侧边栏激活项 |
| `bg-code` | `#f4f4f4` / `#f6f6f6` | 代码块、工具输出背景 |
| `text-primary` | `#1a1a1a` | 正文、标题 |
| `text-body` | `#2a2a2a` | 卡片正文 |
| `text-secondary` | `#555` | 次要文字 |
| `text-muted` | `#888` / `#999` | 标签、辅助信息 |
| `text-thinking` | `#777` | thinking 正文（弱于主文本） |
| `border-default` | `#e0e0e0` | 分割线、边框 |
| `border-input` | `#d0d0d0` | 输入框边框 |
| `border-light` | `#ddd` | 用户气泡边框 |
| `btn-primary` | `#1a1a1a` | 主按钮背景（近黑） |
| `btn-primary-hover` | `#333` | 主按钮 hover |
| `btn-disabled` | `#bbb` | 禁用态按钮 |

### 1.2 语义色（仅限警示/链接，严禁用于装饰）

| Token | 色值 | 用途 |
|---|---|---|
| `semantic-danger` | `#c00` | 错误文字、删除按钮、Stop 按钮 |
| `semantic-danger-bg` | `#fff5f5` | 错误块背景 |
| `semantic-danger-hover` | `#fff0f0` | 删除按钮 hover 背景 |
| `semantic-stop-dimmed` | `rgba(204,0,0,0.6)` | Stop 按钮 waiting 态 |
| `semantic-link` | `#1a56db` | Markdown 超链接（仅此一处） |

> **铁律 1**：除 `semantic-*` 外，不允许出现红/绿/蓝/紫/橙等彩色。绿色、紫色、橙色在任何情况下都不得使用。蓝色仅限超链接。
> **铁律 2**：当卡片具有与页面底色不同的背景时，卡片内部元素不得再使用第二重色差。内部元素应直接使用卡片背景色。
> **铁律 3**：Card 与周围文本之间的 margin 必须保持一致。Card 内部所有子元素的 margin 必须为 0。

---

## 2. 字体与排版

| 属性 | 值 |
|---|---|
| 全局字体 | `system-ui, sans-serif` |
| 等宽字体 | `ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace` |
| 基础字号 | `16px`（浏览器默认） |
| 正文字号 | `0.93rem` |
| 行高（正文） | `1.65` ~ `1.7` |
| 字重（标题/强调） | `600` ~ `700` |
| 字体平滑 | `antialiased`（WebKit）/ `grayscale`（Firefox） |

标签统一使用 `text-transform: uppercase` + `letter-spacing: 0.4~0.6px` 的小号字体（`0.7rem~0.78rem`），颜色为 `text-muted`。

---

## 3. 布局与间距

### 3.1 整体布局

```
┌──────────┬──────────────────────────────────────────┐
│ Sidebar  │  Scroll Area (不限宽)                     │
│ 260px    │    ┌──────────────────────────────┐      │
│ #fafafa  │    │ Chat Area (max-width: 860px) │      │
│          │    │ 居中对齐                      │      │
│          │    └──────────────────────────────┘      │
│          │  #fff                                   │
└──────────┴──────────────────────────────────────────┘
```

- Scroll area：`overflow-y: auto; overflow-x: visible`（允许 commit badge 水平溢出）
- Chat area：`max-width: 860px; margin: 0 auto` 居中
- 左右内边距：`32px`

### 3.2 块间间距

- 卡片之间：`gap: 20px`（由 flex 容器提供）
- 块内子元素：`margin-bottom: 8px`
- 底部留白：`height: 16px` spacer

### 3.3 左对齐规则

所有融入背景的块（assistant、thinking、tool、error）统一 **左内边距 10px**：

```
│ ← 10px → 💡 THINKING
│ ← 10px →   思考内容……
│ ← 10px → 正文内容……
```

| 元素 | 左内边距 |
|---|---|
| `.transcript-card` | `padding-left: 10px` |
| `.thinking-header` | `padding-left: 10px` |
| `.thinking-body` | `padding-left: 10px` |

---

## 4. 组件规范

### 4.1 用户气泡 + Commit Badge

用户气泡右对齐（`align-self: flex-end; max-width: 80%`），外层 `.user-bubble-wrapper` 作为 flex 子元素。

```css
.user-bubble {
    background: #f3f3f3;      /* bg-user */
    border: 1px solid #ddd;   /* border-light */
    border-radius: 12px;
    padding: 14px 18px;
    box-shadow: 0 0 4px hsla(0,0%,60%,0.2);
}
```

**Commit Badge**：绝对定位在气泡右侧 `left: calc(100% + 14px)`，`top: 0`。无背景无边框，仅 `box-shadow` 辉光。默认显示 7 位 short_sha（等宽字体），hover 时向下展开露出 `restore` 按钮。

- 首次点击 "restore" → 变红 "confirm"
- 二次点击确认 → 触发 checkout API

### 4.2 可折叠卡片（CollapsibleCard）

通用组件，用于 tool cards、thinking block。展开/折叠使用 CSS grid 动画：

```css
.tool-card-body {
    display: grid;
    grid-template-rows: 1fr;
    transition: grid-template-rows var(--anim-fast);
}
.tool-card-body--collapsed {
    grid-template-rows: 0fr;
}
.tool-card-body-inner {
    overflow: hidden;
}
```

| Prop | 说明 |
|---|---|
| `headerClickable` | 默认 `true`，`false` 时 header 不可点 |
| `hideChevron` | 默认 `false`，`true` 时隐藏默认 chevron |

### 4.3 Thinking 块

复用 `CollapsibleCard`。`headerClickable={done}`（仅完成后可折叠），复用默认 chevron（`opacity: 0 → 1` on hover）。

- 灯泡图标：`<Icon name="bulb" size={14} />`
- 完成态背景：`#f9f9f9`，`border-radius: 6px`
- 流式生成中：label 有 `think-pulse` 呼吸动画，不可折叠

### 4.4 工具卡片（Tool Cards）

全部方角（`border-radius: 0`），统一折叠高度。Header padding 统一由 `.tool-card-header` 提供（`3px 0`）。

#### Shell（Run Command）
- 深色底 `#1e1e1e`，白字 `#d4d4d4`
- timeout 徽章位于头部最右上角

#### Write / Read
- 浅灰底 `#fafafa`，文件路径显示在头部右侧
- 内容区按文件扩展名识别语言并语法高亮

#### 其他工具
- 默认亮色风格，正文 Markdown 渲染

### 4.5 错误卡片（Error）

使用 `<Icon name="error" size={12} />` SVG 三角警告图标（**禁止 emoji**）。

```css
.error-card .transcript-label {
    color: #c00;           /* semantic-danger */
    display: flex;
    align-items: center;
    gap: 4px;
}
.error-card .transcript-body {
    color: #b00;
    background: #fff5f5;  /* semantic-danger-bg */
    border-left: 3px solid #c00;
}
```

### 4.6 输入栏 + Prefill

Input bar 固定底部，`border-top: 1px solid #e0e0e0`，白底。textarea `#fafafa`，focus 变 `#fff`。

**Prefill**：回溯后弹出在 input bar 上方。`max-height` 动画滑入/滑出，无外边框，textarea 自带 `border-radius: 8px 8px 0 0` + `box-shadow` 辉光。有内容时 Send 按钮联动判空。

**Send 按钮**三态：

| 状态 | 样式 | 行为 |
|---|---|---|
| idle | `#1a1a1a` 近黑 | 发送 |
| running | `#c00` 红底 "Stop" | 中断 |
| interrupting | `#c00` 60% opacity "Stopping…" | 禁用，等待后端 |

### 4.7 侧边栏

- 宽度固定 `260px`，`border-right: 1px solid #e0e0e0`
- "New Session" 按钮：`#1a1a1a`
- 列表项 hover `#eee`，active `#e8e8e8`
- Context menu：白底卡片 + `box-shadow`，Delete 项 `semantic-danger`

### 4.8 Markdown 渲染

- 正文 `#2a2a2a`，内联代码 `#f0f0f0` 背景 `#333` 文字
- 代码块 `#f4f4f4` 背景 + `1px solid #e8e8e8`（不用深色背景）
- 链接 `#1a56db` 带下划线
- 引用块 `border-left: 3px solid #ccc`

---

## 5. 图标系统

### 5.1 图标清单

| name | 用途 |
|---|---|
| `bulb` | thinking 块 |
| `chevron-up` / `chevron-down` | 折叠展开 |
| `dots-vertical` | 侧边栏三点菜单 |
| `tool` | 工具卡片 |
| `write` | Write/Read 文件操作 |
| `error` | 错误块（三角警告） |
| `restore` | commit 回溯按钮 |

### 5.2 图标规范

- 所有图标 `viewBox="0 0 24 24"`
- `stroke="currentColor"`、`strokeWidth={1.5}`、`strokeLinecap="round"`、`strokeLinejoin="round"`、`fill="none"`
- 颜色由 CSS `color` 继承
- **禁止 emoji 作为图标**

---

## 6. 动效

### 6.1 速度令牌

在 `:root` 中定义，所有 `transition` 必须引用令牌：

| Token | 值 | 用途 |
|---|---|---|
| `--anim-leisurely` | `0.35s ease` | prefill 滑入、大面积展开 |
| `--anim-fast` | `0.18s ease` | hover、chevron、卡片折叠、按钮 |
| `--anim-urgent` | `0.08s ease` | 即时反馈、自动置底 |

### 6.2 应用规则

| 场景 | 令牌 |
|---|---|
| CollapsibleCard 折叠/展开 | `--anim-fast` |
| 按钮 hover、chevron 显隐 | `--anim-fast` |
| commit badge hover 展开 | `--anim-fast` |
| prefill 滑入/滑出 | `--anim-leisurely` |
| 自动置底（scrollToBottom） | `behavior: "auto"`（即时） |

### 6.3 关键帧动画

| 场景 | 时长 | 说明 |
|---|---|---|
| `think-pulse` | `1.4s` | thinking 流式呼吸 |
| `tool-icon-pulse` | `1.2s` | 工具图标流式脉冲 |
| `shell-spin` | `0.8s` | Shell spinner |
| `rainbow-glow` | `3s` | click-to-focus 辉光 |

> 不使用弹跳、缩放、旋转等夸张动效。

---

## 7. 交互行为

### 7.1 自动置底

- 新内容到达时，若用户在底部（距底 ≤ 8px），自动滚到底
- 用户手动上滚超过阈值（> 8px）打破 sticky 状态
- 用户滚回底部（距底 ≤ 4px）自动重连 sticky
- 自动滚动为即时（`behavior: "auto"`）

### 7.2 Interrupt（中断）

- 点击 Stop → 前端 `interrupting=true`，仅发 `POST /interrupt`，不 abort SSE
- 等待后端完整清理（LLM 停、工具停、transcript 修复）
- SSE 流自然关闭后 `finally` 清零 `running` + `interrupting`
- 中断后的 error transcript 对 LLM 友好：`"The user interrupted the agent..."`

### 7.3 Click-to-Focus（彩虹辉光）

- 所有带 `data-fid` 的元素可点击聚焦
- 聚焦时添加 `.card-latest` 类，触发 `rainbow-glow` 动画
- 同 `data-fid` 的元素共享聚焦态（用于 tool pair 的双卡）

---

## 8. 禁止事项

- ❌ 彩色（紫/绿/橙/蓝，除 `semantic-*` 和链接）
- ❌ emoji 作为 UI 图标
- ❌ 彩色渐变
- ❌ 融入背景的块使用边框或背景色（error 除外）
- ❌ 卡片内边距不一致
- ❌ 过大的阴影
- ❌ 弹跳/旋转/缩放等夸张动效
- ❌ 硬编码过渡时间 — 必须使用 `--anim-*` 令牌
