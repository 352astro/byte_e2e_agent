# Legacy 清理清单

需要逐步移除的旧代码、命名和兼容层。

---

## 类型层

- [x] `agent/core/types.py` — 删除 `ChunkKind = None`、`ChunkMetadata = None` 占位符
- [ ] `agent/prompts.py` — 删除 re-export stub（已改为显式 `SYSTEM_PROMPT` 导入，待确认无调用方可删）

## Session 兼容层

`agent/session/_data.py` 中的向后兼容方法，实际调用方已迁移到新 API：

- [ ] `get_transcripts()` → 调用方改用 `get_messages()`
- [ ] `add_transcript()` → 调用方改用 `add_message()`
- [ ] `replace_transcripts()` → 调用方改用 `replace_messages()`
- [ ] `truncate_transcripts_by_tid()` → 调用方改用 `truncate_by_id()`
- [ ] `truncate_transcripts_from()` → 确认调用方
- [ ] `_old_transcript_to_message()` → 仅旧 JSONL 加载用到，保留
- [ ] `_LEGACY_KIND_TO_ROLE` → 同上，保留
- [ ] 旧 JSONL 格式加载路径（`_old_record_to_message`、`_raw_openai_to_message`）→ 保留到所有旧数据迁移完毕

## Runtime 兼容层

- [ ] `agent/runtime.py` — 所有 `if isinstance(legacy, Session):` 分支。SessionEntry 已持有 Session 引用，应统一为 `entry.session` 或直接存 Message
- [ ] `agent/runtime.py:191` — `SessionEntry.from_legacy_session(session)` 调用
- [ ] `agent/runtime.py:280` — `TODO(Phase 4)` 注释
- [ ] `agent/runtime.py:97` — `pending_request` 字典键 `transcript_id` → `message_id`
- [ ] `agent/runtime.py:288` — `resolve(transcript_id)` 参数名 → `message_id`

## SessionEntry

- [ ] `agent/session/entry.py:63` — `from_legacy_session()` 方法
- [ ] `agent/session/entry.py:38` — `_data: object | None` 字段（存旧 Session 引用，应改为直接存 Message 列表）

## 错误/修复

- [ ] `agent/errors/__init__.py:14` — `repair_transcripts = repair_messages` 兼容别名
- [ ] `agent/errors/repair.py:110-111` — 同上文件内别名

## 命名清理（transcript → message）

- [ ] `agent/shadow_repo.py` — `transcript_id` 参数名 → `message_id`（101-422 行，约 15 处）
- [ ] `agent/metrics.py` — `transcript_id` 字段名 → `message_id`（schma 列名需迁移）
- [ ] `agent/persistence/schema.py` — `transcript_id TEXT` 列名
- [ ] `agent/hook/metrics_hook.py` — `transcript_id=message_id` 参数传递（不再需要翻译）

## API 层

- [ ] `app/api/sse.py:24-33` — `yield_transcripts_as_flush()` 旧 SSE 格式回放
- [ ] `app/api/routes/chat.py:75-84` — 旧 transcript replay 逻辑（应改为 Message 回放）
- [ ] `app/api/routes/chat.py:100-103` — `_legacy_flush_line()` 旧 SSE 格式
- [x] `app/api/routes/sessions.py:113-121` — `_transcripts` → `_messages`，`reconstruct_tasks` 已移除（P0 修复）
- [ ] `app/schemas/chat.py:10` — `transcript_id` 字段 → `message_id`
- [ ] `app/services/project.py:206` — `session.get_transcripts()` → `session.get_messages()`

## 工具层

- [x] `agent/task/` — 整个目录是 `agent/tools/task.py` 的 re-export，已删除
- [x] `agent/llm_lc.py:1-9` — docstring 已清理

## 已删除（无需处理）

- [x] `agent/transcript.py`
- [x] `agent/sandbox.py`
- [x] `agent/scheduler.py`
- [x] `agent/llm.py`（HelloAgentsLLM）
- [x] `agent/terminal.py`（PersistentTerminal）
- [x] `agent/utils/sysguard.py`
- [x] `agent/tools/base.py`（BaseTool）
- [x] `Sandbox` 类定义 — 已删除（Workspace 统一）
- [x] `TranscriptStream`
- [x] `ChunkKind` / `ChunkMetadata` — 占位符已删除
- [x] `MessageChunk`

## 无依赖的外部清理

- [x] `agent/utils/safety.py` — `check_command_safety` / `safe_resolve_path`，已无调用方（安全检查交给 GuardHook）
- [x] `agent/utils/_term.py` — 终端颜色辅助，LoggingHook 内有内联版本，已删除
