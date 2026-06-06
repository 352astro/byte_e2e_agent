import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import Icon from "./Icon";
import SessionCustomizePanel from "./SessionCustomizePanel";

interface MemoryRecord {
  id: string;
  kind: string;
  content: string;
  feature?: string;
  created_at: number;
  updated_at: number;
  use_count: number;
}

interface SettingsWindowProps {
  workspace: string;
  onClose: () => void;
}

interface ToolInfo {
  name: string;
  description: string;
}

interface SessionRule {
  id: string;
  content: string;
}

interface SessionSettings {
  preamble: string;
  rules: SessionRule[];
  default_rule_ids: string[];
  default_skill_names: string[];
}

interface SkillInfo {
  name: string;
  description: string;
  source: "builtin" | "custom";
  has_builtin: boolean;
  overrides_builtin: boolean;
}

interface SkillDetail extends SkillInfo {
  content: string;
}

interface SysguardRule {
  id: string;
  label: string;
  path: string;
  mode: "readonly" | "readonly_exec" | "readwrite";
  source: "builtin" | "global" | "workspace";
  enabled: boolean;
  description: string;
}

interface SysguardSettingsPayload {
  builtin?: SysguardRule[];
  global?: SysguardRule[];
  workspace?: SysguardRule[];
}

type ToolPermissionMode = "allow" | "ask" | "deny";

const memoryKinds = ["fact", "preference", "decision", "todo", "summary"];

function formatTime(seconds: number): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString();
}

export default function SettingsWindow({
  workspace,
  onClose,
}: SettingsWindowProps) {
  const [position, setPosition] = useState({ x: 300, y: 80 });
  const windowRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
  } | null>(null);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("fact");
  const [activeTab, setActiveTab] = useState<
    "memory" | "rules" | "skills" | "preamble" | "permissions" | "sysguard"
  >("memory");
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [toolPermissions, setToolPermissions] = useState<
    Record<string, ToolPermissionMode>
  >({});
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [activeSkill, setActiveSkill] = useState("");
  const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null);
  const [skillDraftName, setSkillDraftName] = useState("");
  const [skillDraftContent, setSkillDraftContent] = useState("");
  const [sessionSettings, setSessionSettings] =
    useState<SessionSettings | null>(null);
  const [sysguardBuiltin, setSysguardBuiltin] = useState<SysguardRule[]>([]);
  const [sysguardGlobal, setSysguardGlobal] = useState<SysguardRule[]>([]);
  const [sysguardWorkspace, setSysguardWorkspace] = useState<SysguardRule[]>([]);
  const [activeSysguardRule, setActiveSysguardRule] = useState("");
  const [sysguardNewScope, setSysguardNewScope] =
    useState<"global" | "workspace">("workspace");
  const [sysguardDraft, setSysguardDraft] = useState({
    label: "",
    path: "",
    mode: "readonly_exec" as SysguardRule["mode"],
    enabled: true,
    description: "",
  });

  const loadMemories = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/memory");
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: { memories?: MemoryRecord[] } = await res.json();
      setMemories(data.memories || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMemories();
  }, [loadMemories, workspace]);

  const loadPermissions = useCallback(async () => {
    try {
      const [toolsRes, permissionsRes] = await Promise.all([
        fetch("/api/tool-presets"),
        fetch("/api/settings/tool-permissions"),
      ]);
      if (!toolsRes.ok) throw new Error(`Tools returned ${toolsRes.status}`);
      if (!permissionsRes.ok) {
        throw new Error(`Permissions returned ${permissionsRes.status}`);
      }
      const toolsData: { tools?: ToolInfo[] } = await toolsRes.json();
      const permissionData: { tools?: Record<string, ToolPermissionMode> } =
        await permissionsRes.json();
      setTools(toolsData.tools || []);
      setToolPermissions(permissionData.tools || {});
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void loadPermissions();
  }, [loadPermissions, workspace]);

  const loadSysguard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/settings/sysguard");
      if (!res.ok) throw new Error(`Sysguard returned ${res.status}`);
      const data: SysguardSettingsPayload = await res.json();
      const builtin = data.builtin || [];
      const globalRules = data.global || [];
      const workspaceRules = data.workspace || [];
      setSysguardBuiltin(builtin);
      setSysguardGlobal(globalRules);
      setSysguardWorkspace(workspaceRules);
      setActiveSysguardRule((current) => {
        if (current === "__new__") return current;
        const editable = [...workspaceRules, ...globalRules];
        if (current && editable.some((rule) => rule.id === current)) return current;
        if (current && builtin.some((rule) => rule.id === current)) return current;
        return workspaceRules[0]?.id || globalRules[0]?.id || builtin[0]?.id || "";
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "sysguard") void loadSysguard();
  }, [activeTab, loadSysguard, workspace]);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    try {
      const [skillsRes, settingsRes] = await Promise.all([
        fetch("/api/skills"),
        fetch("/api/settings/session-defaults"),
      ]);
      if (!skillsRes.ok) throw new Error(`Skills returned ${skillsRes.status}`);
      if (!settingsRes.ok) {
        throw new Error(`Settings returned ${settingsRes.status}`);
      }
      const skillsData: { skills?: SkillInfo[] } = await skillsRes.json();
      const settingsData: SessionSettings = await settingsRes.json();
      const items = skillsData.skills || [];
      setSkills(items);
      setSessionSettings(settingsData);
      setActiveSkill((current) => {
        if (current === "__new__") return current;
        if (current && items.some((skill) => skill.name === current)) {
          return current;
        }
        return items[0]?.name || "";
      });
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "skills") void loadSkills();
  }, [activeTab, loadSkills, workspace]);

  useEffect(() => {
    if (activeTab !== "skills" || !activeSkill || activeSkill === "__new__") {
      return;
    }
    let cancelled = false;
    const loadDetail = async () => {
      try {
        const res = await fetch(`/api/skills/${encodeURIComponent(activeSkill)}`);
        if (!res.ok) throw new Error(`Skill returned ${res.status}`);
        const data: SkillDetail = await res.json();
        if (cancelled) return;
        setSkillDetail(data);
        setSkillDraftName(data.name);
        setSkillDraftContent(data.content);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [activeTab, activeSkill]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const startDrag = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button")) return;
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: position.x,
      originY: position.y,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const moveDrag = (e: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const rect = windowRef.current?.getBoundingClientRect();
    const width = rect?.width || 680;
    const height = rect?.height || 420;
    const maxX = Math.max(16, window.innerWidth - width - 16);
    const maxY = Math.max(16, window.innerHeight - height - 16);
    setPosition({
      x: Math.min(Math.max(16, drag.originX + e.clientX - drag.startX), maxX),
      y: Math.min(Math.max(16, drag.originY + e.clientY - drag.startY), maxY),
    });
  };

  const stopDrag = (e: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === e.pointerId) {
      dragRef.current = null;
    }
  };

  const addMemory = async () => {
    const trimmed = content.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      const res = await fetch("/api/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: trimmed, kind }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setContent("");
      await loadMemories();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const deleteMemory = async (id: string) => {
    try {
      const res = await fetch(`/api/memory/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      setMemories((items) => items.filter((item) => item.id !== id));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const updateToolPermission = async (
    toolName: string,
    mode: ToolPermissionMode,
  ) => {
    const next = { ...toolPermissions, [toolName]: mode };
    setToolPermissions(next);
    try {
      const res = await fetch("/api/settings/tool-permissions", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tools: next }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const saved: { tools?: Record<string, ToolPermissionMode> } =
        await res.json();
      setToolPermissions(saved.tools || {});
      setError(null);
    } catch (err) {
      setToolPermissions(toolPermissions);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const toggleDefaultSkill = async (name: string) => {
    if (!sessionSettings) return;
    const selected = new Set(sessionSettings.default_skill_names || []);
    if (selected.has(name)) selected.delete(name);
    else selected.add(name);
    const next = {
      ...sessionSettings,
      default_skill_names: Array.from(selected).sort(),
    };
    setSessionSettings(next);
    try {
      const res = await fetch("/api/settings/session-defaults", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const saved: SessionSettings = await res.json();
      setSessionSettings(saved);
      setError(null);
    } catch (err) {
      setSessionSettings(sessionSettings);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const newSkill = () => {
    setActiveSkill("__new__");
    setSkillDetail(null);
    setSkillDraftName("");
    setSkillDraftContent("# New Skill\n\nDescribe when and how to use this skill.");
  };

  const saveSkill = async () => {
    const name =
      activeSkill === "__new__" ? skillDraftName.trim() : activeSkill.trim();
    if (!name || !skillDraftContent.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(
        activeSkill === "__new__"
          ? "/api/skills"
          : `/api/skills/${encodeURIComponent(name)}`,
        {
          method: activeSkill === "__new__" ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            content: skillDraftContent,
          }),
        },
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Server returned ${res.status}`);
      }
      const saved: SkillDetail = await res.json();
      setActiveSkill(saved.name);
      setSkillDetail(saved);
      setSkillDraftName(saved.name);
      setSkillDraftContent(saved.content);
      await loadSkills();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const deleteOrRestoreSkill = async () => {
    if (!skillDetail || skillDetail.source !== "custom") return;
    const restore = skillDetail.has_builtin;
    setSaving(true);
    try {
      const res = await fetch(
        restore
          ? `/api/skills/${encodeURIComponent(skillDetail.name)}/restore-default`
          : `/api/skills/${encodeURIComponent(skillDetail.name)}`,
        { method: restore ? "POST" : "DELETE" },
      );
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      if (restore) {
        const restored: SkillDetail = await res.json();
        setSkillDetail(restored);
        setSkillDraftContent(restored.content);
        setActiveSkill(restored.name);
      } else {
        setActiveSkill("");
        setSkillDetail(null);
        setSkillDraftName("");
        setSkillDraftContent("");
      }
      await loadSkills();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const selectSysguardRule = (rule: SysguardRule) => {
    setActiveSysguardRule(rule.id);
    setSysguardDraft({
      label: rule.label,
      path: rule.path,
      mode: rule.mode,
      enabled: rule.enabled,
      description: rule.description || "",
    });
  };

  const newSysguardRule = () => {
    setActiveSysguardRule("__new__");
    setSysguardNewScope("workspace");
    setSysguardDraft({
      label: "",
      path: "",
      mode: "readonly" as SysguardRule["mode"],
      enabled: true,
      description: "",
    });
  };

  const findSysguardRule = (ruleId: string) =>
    [...sysguardWorkspace, ...sysguardGlobal, ...sysguardBuiltin].find(
      (rule) => rule.id === ruleId,
    ) || null;

  const applySysguardPayload = (data: SysguardSettingsPayload) => {
    setSysguardBuiltin(data.builtin || []);
    setSysguardGlobal(data.global || []);
    setSysguardWorkspace(data.workspace || []);
  };

  const saveSysguardRule = async () => {
    const isNew = activeSysguardRule === "__new__";
    const activeRule = findSysguardRule(activeSysguardRule);
    const scope = isNew ? sysguardNewScope : activeRule?.source;
    if (scope !== "global" && scope !== "workspace") return;
    if (!sysguardDraft.label.trim() || !sysguardDraft.path.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(
        isNew
          ? `/api/settings/sysguard/${scope}`
          : `/api/settings/sysguard/${scope}/${encodeURIComponent(activeSysguardRule)}`,
        {
          method: isNew ? "POST" : "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(sysguardDraft),
        },
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Server returned ${res.status}`);
      }
      const data: SysguardSettingsPayload = await res.json();
      applySysguardPayload(data);
      const list = scope === "workspace" ? data.workspace || [] : data.global || [];
      setActiveSysguardRule(
        isNew ? list[list.length - 1]?.id || "" : activeSysguardRule,
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const deleteSysguardRule = async () => {
    if (!activeSysguardRule || activeSysguardRule === "__new__") return;
    const activeRule = findSysguardRule(activeSysguardRule);
    const scope = activeRule?.source;
    if (scope !== "global" && scope !== "workspace") return;
    setSaving(true);
    try {
      const res = await fetch(
        `/api/settings/sysguard/${scope}/${encodeURIComponent(activeSysguardRule)}`,
        { method: "DELETE" },
      );
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data: SysguardSettingsPayload = await res.json();
      applySysguardPayload(data);
      const next =
        data.workspace?.[0] || data.global?.[0] || data.builtin?.[0] || null;
      if (next) selectSysguardRule(next);
      else newSysguardRule();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const renderSysguardSettings = () => {
    const builtinActive = sysguardBuiltin.find(
      (rule) => rule.id === activeSysguardRule,
    );
    const globalActive = sysguardGlobal.find(
      (rule) => rule.id === activeSysguardRule,
    );
    const workspaceActive = sysguardWorkspace.find(
      (rule) => rule.id === activeSysguardRule,
    );
    const activeRule = workspaceActive || globalActive || builtinActive || null;
    const isNew = activeSysguardRule === "__new__";
    const editable =
      isNew || activeRule?.source === "global" || activeRule?.source === "workspace";
    const renderEditableRule = (rule: SysguardRule) => (
      <div
        className={`skill-library-item ${activeSysguardRule === rule.id ? "active" : ""}`}
        key={rule.id}
        role="button"
        tabIndex={0}
        onClick={() => selectSysguardRule(rule)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            selectSysguardRule(rule);
          }
        }}
      >
        <input
          type="checkbox"
          checked={rule.enabled}
          onChange={(e) => {
            e.stopPropagation();
            void fetch(
              `/api/settings/sysguard/${rule.source}/${encodeURIComponent(rule.id)}`,
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  label: rule.label,
                  path: rule.path,
                  mode: rule.mode,
                  enabled: e.target.checked,
                  description: rule.description,
                }),
              },
            ).then(() => loadSysguard());
          }}
          onClick={(e) => e.stopPropagation()}
        />
        <span className="skill-library-name">{rule.label}</span>
        <span className="skill-source skill-source--custom">{rule.mode}</span>
      </div>
    );
    return (
      <div className="sysguard-panel">
        <div className="memory-panel-head">
          <div>
            <h2>Shell Sandbox</h2>
            <div className="memory-workspace">
              Read/execute allowlist for shell toolchains.
            </div>
          </div>
          <button
            className="settings-refresh-btn"
            type="button"
            onClick={() => void loadSysguard()}
            disabled={loading}
          >
            {loading ? "Loading" : "Refresh"}
          </button>
        </div>
        {error && <div className="memory-error">{error}</div>}
        <div className="skill-library-layout">
          <aside className="skill-library-sidebar">
            <button
              className={`skill-library-new ${isNew ? "active" : ""}`}
              type="button"
              onClick={newSysguardRule}
            >
              + New Rule
            </button>
            {sysguardWorkspace.length > 0 && (
              <div className="sysguard-section-label">Workspace</div>
            )}
            {sysguardWorkspace.map(renderEditableRule)}
            {sysguardGlobal.length > 0 && (
              <div className="sysguard-section-label">Global</div>
            )}
            {sysguardGlobal.map(renderEditableRule)}
            {sysguardBuiltin.length > 0 && (
              <div className="sysguard-section-label">Built-in</div>
            )}
            {sysguardBuiltin.map((rule) => (
              <div
                className={`skill-library-item ${activeSysguardRule === rule.id ? "active" : ""}`}
                key={rule.id}
                role="button"
                tabIndex={0}
                onClick={() => selectSysguardRule(rule)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    selectSysguardRule(rule);
                  }
                }}
              >
                <span className="skill-library-name">{rule.label}</span>
                <span className="skill-source skill-source--builtin">
                  {rule.mode}
                </span>
              </div>
            ))}
          </aside>
          <section className="skill-library-editor">
            {!isNew && !activeRule ? (
              <div className="memory-empty">Select a rule.</div>
            ) : (
              <>
                {isNew && (
                  <label className="skill-field">
                    <span>Scope</span>
                    <select
                      value={sysguardNewScope}
                      onChange={(e) =>
                        setSysguardNewScope(
                          e.target.value as "global" | "workspace",
                        )
                      }
                    >
                      <option value="workspace">Current workspace</option>
                      <option value="global">Global</option>
                    </select>
                  </label>
                )}
                {!isNew && activeRule && (
                  <div className="sysguard-scope-badge">
                    Scope: {activeRule.source}
                  </div>
                )}
                <label className="skill-field">
                  <span>Label</span>
                  <input
                    value={isNew || editable ? sysguardDraft.label : activeRule?.label || ""}
                    onChange={(e) =>
                      setSysguardDraft((draft) => ({
                        ...draft,
                        label: e.target.value,
                      }))
                    }
                    disabled={!editable}
                  />
                </label>
                <label className="skill-field">
                  <span>Path</span>
                  <input
                    value={isNew || editable ? sysguardDraft.path : activeRule?.path || ""}
                    onChange={(e) =>
                      setSysguardDraft((draft) => ({
                        ...draft,
                        path: e.target.value,
                      }))
                    }
                    disabled={!editable}
                  />
                </label>
                <label className="skill-field">
                  <span>Mode</span>
                  <select
                    value={
                      isNew || editable
                        ? sysguardDraft.mode
                        : activeRule?.mode || "readonly_exec"
                    }
                    onChange={(e) =>
                      setSysguardDraft((draft) => ({
                        ...draft,
                        mode: e.target.value as SysguardRule["mode"],
                      }))
                    }
                    disabled={!editable}
                  >
                    <option value="readonly">Read only</option>
                    <option value="readonly_exec">Read + execute</option>
                    <option value="readwrite">Read + write</option>
                  </select>
                </label>
                <label className="skill-field">
                  <span>Description</span>
                  <textarea
                    value={
                      isNew || editable
                        ? sysguardDraft.description
                        : activeRule?.description || ""
                    }
                    onChange={(e) =>
                      setSysguardDraft((draft) => ({
                        ...draft,
                        description: e.target.value,
                      }))
                    }
                    disabled={!editable}
                    rows={4}
                  />
                </label>
                <label className="sysguard-toggle">
                  <input
                    type="checkbox"
                    checked={isNew || editable ? sysguardDraft.enabled : true}
                    onChange={(e) =>
                      setSysguardDraft((draft) => ({
                        ...draft,
                        enabled: e.target.checked,
                      }))
                    }
                    disabled={!editable}
                  />
                  Enabled
                </label>
                <div className="skill-actions">
                  {editable && (
                    <button
                      className="memory-add-btn"
                      type="button"
                      onClick={() => void saveSysguardRule()}
                      disabled={
                        saving ||
                        !sysguardDraft.label.trim() ||
                        !sysguardDraft.path.trim()
                      }
                    >
                      {saving ? "Saving" : isNew ? "Create Rule" : "Save"}
                    </button>
                  )}
                  {(activeRule?.source === "global" ||
                    activeRule?.source === "workspace") && (
                    <button
                      className="memory-delete-btn skill-danger-btn"
                      type="button"
                      onClick={() => void deleteSysguardRule()}
                      disabled={saving}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    );
  };

  const renderSkillsLibrary = () => {
    const selected = new Set(sessionSettings?.default_skill_names || []);
    const isNew = activeSkill === "__new__";
    return (
      <div className="skill-library">
        <div className="memory-panel-head">
          <div>
            <h2>Skills</h2>
            <div className="memory-workspace">
              Built-in skills are protected. Custom skills override by name.
            </div>
          </div>
          <button
            className="settings-refresh-btn"
            type="button"
            onClick={() => void loadSkills()}
            disabled={loading}
          >
            {loading ? "Loading" : "Refresh"}
          </button>
        </div>

        {error && <div className="memory-error">{error}</div>}

        <div className="skill-library-layout">
          <aside className="skill-library-sidebar">
            <button
              className={`skill-library-new ${isNew ? "active" : ""}`}
              type="button"
              onClick={newSkill}
            >
              + New Skill
            </button>
            {skills.map((skill) => (
              <div
                className={`skill-library-item ${activeSkill === skill.name ? "active" : ""}`}
                key={skill.name}
                role="button"
                tabIndex={0}
                onClick={() => setActiveSkill(skill.name)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setActiveSkill(skill.name);
                  }
                }}
              >
                <input
                  type="checkbox"
                  checked={selected.has(skill.name)}
                  onChange={(e) => {
                    e.stopPropagation();
                    void toggleDefaultSkill(skill.name);
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
                <span className="skill-library-name">{skill.name}</span>
                <span className={`skill-source skill-source--${skill.source}`}>
                  {skill.overrides_builtin
                    ? "override"
                    : skill.source}
                </span>
              </div>
            ))}
          </aside>

          <section className="skill-library-editor">
            {isNew ? (
              <label className="skill-field">
                <span>Name</span>
                <input
                  value={skillDraftName}
                  onChange={(e) => setSkillDraftName(e.target.value)}
                  placeholder="my-custom-skill"
                />
              </label>
            ) : skillDetail ? (
              <div className="skill-editor-head">
                <div>
                  <h3>{skillDetail.name}</h3>
                  <p>{skillDetail.description || "No description."}</p>
                </div>
                <span className={`skill-source skill-source--${skillDetail.source}`}>
                  {skillDetail.overrides_builtin
                    ? "custom override"
                    : skillDetail.source}
                </span>
              </div>
            ) : (
              <div className="memory-empty">Select a skill.</div>
            )}

            {(isNew || skillDetail) && (
              <>
                <label className="skill-field skill-field--content">
                  <span>SKILL.md</span>
                  <textarea
                    value={skillDraftContent}
                    onChange={(e) => setSkillDraftContent(e.target.value)}
                    spellCheck={false}
                  />
                </label>
                <div className="skill-actions">
                  <button
                    className="memory-add-btn"
                    type="button"
                    onClick={() => void saveSkill()}
                    disabled={
                      saving ||
                      !skillDraftContent.trim() ||
                      (isNew && !skillDraftName.trim())
                    }
                  >
                    {saving
                      ? "Saving"
                      : isNew
                        ? "Create Skill"
                        : skillDetail?.source === "builtin"
                          ? "Save Custom Override"
                          : "Save"}
                  </button>
                  {skillDetail?.source === "custom" && (
                    <button
                      className="memory-delete-btn skill-danger-btn"
                      type="button"
                      onClick={() => void deleteOrRestoreSkill()}
                      disabled={saving}
                    >
                      {skillDetail.has_builtin ? "Restore Default" : "Delete"}
                    </button>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    );
  };

  return (
    <div
      ref={windowRef}
      className="settings-window"
      style={{ left: position.x, top: position.y }}
    >
      <div
        className="settings-titlebar"
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <div className="settings-title">Settings</div>
        <button className="settings-close-btn" type="button" onClick={onClose}>
          x
        </button>
      </div>

      <div className="settings-body">
        <aside className="settings-nav">
          <button
            className={`settings-nav-item ${activeTab === "memory" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("memory")}
          >
            Long-term Memory
          </button>
          <button
            className={`settings-nav-item ${activeTab === "rules" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("rules")}
          >
            Rules
          </button>
          <button
            className={`settings-nav-item ${activeTab === "skills" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("skills")}
          >
            Skills
          </button>
          <button
            className={`settings-nav-item ${activeTab === "preamble" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("preamble")}
          >
            Preamble
          </button>
          <button
            className={`settings-nav-item ${activeTab === "permissions" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("permissions")}
          >
            Permissions
          </button>
          <button
            className={`settings-nav-item ${activeTab === "sysguard" ? "active" : ""}`}
            type="button"
            onClick={() => setActiveTab("sysguard")}
          >
            Shell Sandbox
          </button>
        </aside>

        <main className="settings-content">
          {activeTab === "memory" ? (
            <>
              <div className="memory-panel-head">
                <div>
                  <h2>Long-term Memory</h2>
                  <div className="memory-workspace" title={workspace}>
                    {workspace || "Current workspace"}
                  </div>
                </div>
                <button
                  className="settings-refresh-btn"
                  type="button"
                  onClick={() => void loadMemories()}
                  disabled={loading}
                >
                  {loading ? "Loading" : "Refresh"}
                </button>
              </div>

              <div className="memory-add-row">
                <select
                  className="memory-kind-select"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  {memoryKinds.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <textarea
                  className="memory-input"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Add a memory for this workspace"
                  rows={3}
                />
                <button
                  className="memory-add-btn"
                  type="button"
                  onClick={() => void addMemory()}
                  disabled={saving || !content.trim()}
                >
                  Add
                </button>
              </div>

              {error && <div className="memory-error">{error}</div>}

              <div className="memory-list">
                {memories.length === 0 && !loading && (
                  <div className="memory-empty">No memory yet.</div>
                )}
                {memories.map((memory) => (
                  <div className="memory-item" key={memory.id}>
                    <div className="memory-item-main">
                      <div className="memory-meta">
                        <span>{memory.kind}</span>
                        <span>{formatTime(memory.updated_at)}</span>
                        {memory.use_count > 0 && (
                          <span>used {memory.use_count}</span>
                        )}
                      </div>
                      <div className="memory-content">{memory.content}</div>
                      {memory.feature && memory.feature !== memory.content && (
                        <div className="memory-feature">{memory.feature}</div>
                      )}
                    </div>
                    <button
                      className="memory-delete-btn"
                      type="button"
                      title="Delete memory"
                      onClick={() => void deleteMemory(memory.id)}
                    >
                      <Icon name="trash" size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </>
          ) : activeTab === "skills" ? (
            renderSkillsLibrary()
          ) : activeTab === "permissions" ? (
            <div className="permissions-panel">
              <div className="memory-panel-head">
                <div>
                  <h2>Tool Permissions</h2>
                  <div className="memory-workspace">
                    Global emergency controls for this workspace.
                  </div>
                </div>
                <button
                  className="settings-refresh-btn"
                  type="button"
                  onClick={() => void loadPermissions()}
                >
                  Refresh
                </button>
              </div>
              {error && <div className="memory-error">{error}</div>}
              <div className="permissions-list">
                {tools.map((tool) => (
                  <div className="permission-row" key={tool.name}>
                    <div className="permission-main">
                      <div className="permission-name">{tool.name}</div>
                      <div className="permission-description">
                        {tool.description || "No description."}
                      </div>
                    </div>
                    <select
                      value={toolPermissions[tool.name] || "allow"}
                      onChange={(e) =>
                        void updateToolPermission(
                          tool.name,
                          e.target.value as ToolPermissionMode,
                        )
                      }
                    >
                      <option value="allow">Allow</option>
                      <option value="ask">Ask</option>
                      <option value="deny">Deny</option>
                    </select>
                  </div>
                ))}
              </div>
            </div>
          ) : activeTab === "sysguard" ? (
            renderSysguardSettings()
          ) : (
            <SessionCustomizePanel
              mode="settings"
              section={activeTab}
            />
          )}
        </main>
      </div>
    </div>
  );
}
