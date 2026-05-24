# UI Design System — Monochrome Agent Interface

> **生效日期**：2026-05-23
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
| `semantic-danger` | `#c00` | 错误文字、删除按钮、错误左边框 |
| `semantic-danger-bg` | `#fff5f5` | 错误块背景 |
| `semantic-danger-hover` | `#fff0f0` | 删除按钮 hover 背景 |
| `semantic-link` | `#1a56db` | Markdown 超链接（仅此一处） |

> **铁律 1**：除 `semantic-*` 外，不允许出现红/绿/蓝/紫/橙等彩色。绿色、紫色、橙色在任何情况下都不得使用。蓝色仅限超链接。
> **铁律 2**：当卡片具有与页面底色不同的背景时，卡片内部元素不得再使用第二重色差（即不得在有色卡片内再嵌套不同背景色的子元素）。内部元素应直接使用卡片背景色。
> **铁律 3**：Card 与周围文本之间的 margin 必须保持一致。若 Card 内部有多层嵌套，仅 Card 自身拥有 margin，内部所有子元素的 margin 必须为 0。

---

## 2. 字体与排版

| 属性 | 值 |
|---|---|
| 全局字体 | `system-ui, sans-serif` |
| 等宽字体 | `ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace` |
| 基础字号 | `16px`（浏览器默认） |
| 正文字号 | `0.93rem`（约 14.9px） |
| 行高（正文） | `1.65` ~ `1.7` |
| 字重（标题/强调） | `600` ~ `700` |
| 字体平滑 | `antialiased`（WebKit）/ `grayscale`（Firefox） |

标签统一使用 `text-transform: uppercase` + `letter-spacing: 0.4~0.6px` 的小号字体（`0.7rem~0.78rem`），颜色为 `text-muted`。

---

## 3. 布局与间距

### 3.1 整体布局

```
┌──────────┬──────────────────────────────────┐
│ Sidebar  │  Main Content (max-width: 860px) │
│ 260px    │  居中对齐，左右 32px 内边距       │
│ #fafafa  │  #fff                            │
└──────────┴──────────────────────────────────┘
```

### 3.2 块间间距

- 卡片之间：`gap: 20px`（由 flex 容器提供）
- 块内子元素：`margin-bottom: 8px`（thinking 与正文之间）
- 底部留白：`height: 16px` spacer

### 3.3 左对齐规则（核心）

所有"融入背景"的块（assistant、thinking、tool result、error、fallback）统一 **左内边距 10px**，确保文字沿同一条竖线对齐：

```
│ ← 10px → 💡 thinking
│ ← 10px →   思考内容……
│ ← 10px → 正文内容……
```

| 元素 | 左内边距 |
|---|---|
| `.transcript-card` | `padding-left: 10px` |
| `.thinking-header` | `padding-left: 10px` |
| `.thinking-body` | `padding-left: 10px; padding-right: 10px` |

chevron 折叠箭头定位在 `right: 8px`（右内边距内）。

---

## 4. 组件规范

### 4.1 用户气泡（唯一带容器的元素）

```css
.user-bubble {
    background: #f3f3f3;      /* bg-user */
    border: 1px solid #ddd;   /* border-light */
    border-radius: 12px;
    padding: 14px 18px;
    align-self: flex-end;     /* 右对齐 */
    max-width: 80%;
}
```

- **不允许**给用户气泡使用彩色边框或彩色背景
- 标签 `YOU`：大写、小号、`#888`

### 4.2 Assistant / Tool / Error 卡片（融入背景）

- **无背景色**、**无边框**（融入 `#fff` 页面底色）
- 仅 error 例外：`border-left: 3px solid #c00` + `background: #fff5f5`（语义红）
- 卡片间距由 flex `gap: 20px` 提供，卡片自身 `padding: 4px 0 4px 10px`

### 4.3 Thinking 块

```
┌─────────────────────────────────────────┐
│ 💡 THINKING                        ▴/▾  │  ← header（hover 时 ▴▾ 可见）
├─────────────────────────────────────────┤
│ 思考内容……                              │  ← body（折叠时隐藏）
└─────────────────────────────────────────┘
```

**行为**：
| 状态 | 展开/折叠 | chevron 可见性 |
|---|---|---|
| 流式生成中 | 强制展开 | 无（不可手动折叠） |
| 生成完毕 | **默认折叠** | hover 时出现（`opacity: 0 → 1`） |
| 用户手动展开 | 展开 | 始终可见 |

**样式**：
- 完成态背景：`#f9f9f9`（`bg-subtle`），`border-radius: 6px`
- 灯泡图标：`<Icon name="bulb" size={14} />`，颜色 `#999`（完成态 `#aaa`）
- thinking 正文：`#777`，比主文本弱化
- 流式生成中：label 有 `think-pulse` 呼吸动画

### 4.4 输入栏

- 固定底部，`border-top: 1px solid #e0e0e0`，白底
- textarea：`#fafafa` 背景，focus 时变 `#fff` + `border-color: #555` + 微弱 `box-shadow`
- 发送按钮：`#1a1a1a` 近黑背景，白色文字，`border-radius: 8px`，disabled 时 `#bbb`

### 4.5 侧边栏

- 宽度固定 `260px`，`border-right: 1px solid #e0e0e0`
- "New Session" 按钮：`#1a1a1a` 近黑背景，白色文字
- 列表项：hover `#eee`，active `#e8e8e8`（深灰，绝不使用彩色）
- 三点菜单按钮：透明底，hover `#e0e0e0`，图标为 `<Icon name="dots-vertical" />`
- Context menu：白底卡片，`box-shadow`，Delete 项使用 `semantic-danger` 色

### 4.6 Markdown 渲染

- 正文：`#2a2a2a`，行高 `1.7`
- 内联代码：`#f0f0f0` 背景，`#333` 文字
- 代码块：`#f4f4f4` 背景 + `1px solid #e8e8e8` 边框（不用深色背景）
- 链接：`#1a56db`，带下划线
- 引用块：`border-left: 3px solid #ccc`，`#666` 文字，斜体
- 表格：边框 `#ddd`，表头 `#f6f6f6`


### 4.7 工具卡片（Tool Cards）

**流式卡片**（构建中）与 **独立卡片**（完成态）均使用 **方角**（`border-radius: 0`）。

#### Shell
- 深色底 `#1e1e1e`，白字 `#d4d4d4`
- 头部 `#2a2a2a`，底部边框 `#333`
- timeout 徽章位于头部**最右上角**（`margin-left: auto`），`background: #333`，方角
- 输出区使用等宽字体，`padding: 12px 14px`

#### Write / Read
- 浅灰底 `#fafafa`，头部 `#f3f3f3`，底部边框 `#e8e8e8`
- 文件路径显示在头部右侧，等宽字体
- 内容区根据文件扩展名识别语言（`.py`, `.ts`, `.md` 等），使用对应语法高亮
- 无法识别时默认使用 Markdown 渲染

#### 其他工具
- 与 Write/Read 相同亮色风格，头部显示工具名
- 正文使用 Markdown 渲染

> **新增禁止事项**：工具卡片不得使用圆角（`border-radius` 必须为 `0`）。

---

---

## 5. 图标系统

### 5.1 组件

所有矢量图标通过 `<Icon>` 组件统一管理：

```tsx
import Icon from "./components/Icon";

<Icon name="bulb" size={14} />
<Icon name="chevron-up" size={10} />
<Icon name="chevron-down" size={10} />
<Icon name="dots-vertical" size={16} />
```

### 5.2 图标规范

- 所有图标共用 `viewBox="0 0 24 24"`
- 线条风格：`stroke="currentColor"`、`strokeWidth={1.5}`、`strokeLinecap="round"`、`strokeLinejoin="round"`、`fill="none"`
- 颜色由 CSS `color` 属性继承，天然适配黑白灰
- **禁止使用 emoji 作为图标**，必须使用 `<Icon>` 或等价的 SVG 线条图

### 5.3 新增图标

1. 设计或选取符合 `24×24` 画布、`1.5px` 线宽的 SVG path
2. 在 `Icon.tsx` 的 `paths` 字典中添加条目
3. 同时在 `IconName` 类型中注册

---

## 6. 动效

| 场景 | 效果 |
|---|---|
| 按钮 hover | `background` / `border-color` 0.15s |
| thinking 流式脉冲 | `think-pulse` 1.4s ease-in-out（label 透明度呼吸） |
| chevron 显示/隐藏 | `opacity` 0.15s（hover 触发） |
| sidebar 列表项 | `background` 0.1s |

- **不使用**弹跳、缩放、旋转等夸张动效
- 过渡时间统一 `0.15s`（微交互），脉冲 `1.4s`（唯一例外）

---

## 7. 禁止事项

- ❌ 紫色（`#7c3aed` 及其任何变体）
- ❌ 绿色（包括 `#f0fdf4` 等浅绿背景）
- ❌ emoji 作为 UI 图标（灯泡、箭头、三点等必须用 SVG）
- ❌ 彩色渐变
- ❌ 融入背景的块使用边框或彩色背景（error 除外）
- ❌ 卡片内边距不一致导致文字不对齐
- ❌ 过大的阴影（仅在 context menu 使用 `0 4px 16px rgba(0,0,0,0.1)`）
