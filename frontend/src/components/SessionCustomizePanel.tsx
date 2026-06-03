import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import type {
  CreateSessionRequest,
  SessionRule,
  SessionSettings,
  SkillInfoResponse,
  ToolInfoResponse,
  ToolPresetListResponse,
  ToolPresetResponse,
  ToolSetPreset,
} from "../types";

type SettingsSection = "rules" | "skills" | "preamble";

interface SessionCustomizePanelProps {
  value?: CreateSessionRequest;
  onChange?: (next: CreateSessionRequest) => void;
  mode?: "create" | "settings";
  section?: SettingsSection;
  readonly?: boolean;
}

const emptyConfig: CreateSessionRequest = {
  name: "",
  preamble: "",
  rules: [],
  preloaded_skills: [],
  tool_set_preset: "all",
  custom_tools: [],
};

const emptySettings: SessionSettings = {
  preamble: "",
  rules: [],
  default_rule_ids: [],
  default_skill_names: [],
};

function normalizeConfig(config?: CreateSessionRequest): CreateSessionRequest {
  return {
    name: config?.name || "",
    preamble: config?.preamble || "",
    rules: config?.rules || [],
    preloaded_skills: config?.preloaded_skills || [],
    tool_set_preset: config?.tool_set_preset || "all",
    custom_tools: config?.custom_tools || [],
  };
}

function normalizeSettings(settings?: SessionSettings): SessionSettings {
  return {
    preamble: settings?.preamble || "",
    rules: settings?.rules || [],
    default_rule_ids: settings?.default_rule_ids || [],
    default_skill_names: settings?.default_skill_names || [],
  };
}

function configFromSettings(settings: SessionSettings): CreateSessionRequest {
  const selectedRules = new Set(settings.default_rule_ids || []);
  return {
    ...emptyConfig,
    preamble: settings.preamble || "",
    rules: (settings.rules || [])
      .filter((rule) => selectedRules.has(rule.id))
      .map((rule) => rule.content),
    preloaded_skills: settings.default_skill_names || [],
  };
}

function toolPresetLabel(preset: ToolSetPreset): string {
  switch (preset) {
    case "all":
      return "All";
    case "minimal":
      return "Minimal";
    case "code_only":
      return "Code Only";
    case "review_only":
      return "Review Only";
    case "custom":
      return "Custom";
    default:
      return preset;
  }
}

export default function SessionCustomizePanel({
  value,
  onChange,
  mode = "create",
  section = "rules",
  readonly = false,
}: SessionCustomizePanelProps) {
  const [settings, setSettings] = useState<SessionSettings>(emptySettings);
  const [skills, setSkills] = useState<SkillInfoResponse[]>([]);
  const [toolPresets, setToolPresets] = useState<ToolPresetResponse[]>([]);
  const [tools, setTools] = useState<ToolInfoResponse[]>([]);
  const [activeSkill, setActiveSkill] = useState("");
  const [activeTool, setActiveTool] = useState("");
  const [customToolDraft, setCustomToolDraft] = useState<string[]>([]);
  const [newRule, setNewRule] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const appliedDefaultsRef = useRef(false);
  const modeRef = useRef(mode);
  const readonlyRef = useRef(readonly);
  const onChangeRef = useRef(onChange);
  const valueRef = useRef(value);
  const config = normalizeConfig(value);

  useEffect(() => {
    modeRef.current = mode;
    readonlyRef.current = readonly;
    onChangeRef.current = onChange;
    valueRef.current = value;
  }, [mode, readonly, onChange, value]);

  const selectedRuleIds = useMemo(
    () => new Set(settings.default_rule_ids || []),
    [settings.default_rule_ids],
  );
  const selectedSkillNames = useMemo(
    () => new Set(settings.default_skill_names || []),
    [settings.default_skill_names],
  );
  const activeSkillInfo = useMemo(
    () => skills.find((skill) => skill.name === activeSkill) || skills[0],
    [activeSkill, skills],
  );
  const selectedToolNames = useMemo(
    () => new Set(config.custom_tools || []),
    [config.custom_tools],
  );
  const activeToolInfo = useMemo(
    () => tools.find((tool) => tool.name === activeTool) || tools[0],
    [activeTool, tools],
  );
  const presetTools = useMemo(() => {
    const preset = toolPresets.find(
      (item) => item.name === config.tool_set_preset,
    );
    return preset?.tools || [];
  }, [config.tool_set_preset, toolPresets]);

  const emitCreateConfig = useCallback(
    (
      nextSettings: SessionSettings,
      partial?: Partial<CreateSessionRequest>,
      baseValue: CreateSessionRequest | undefined = value,
    ) => {
      if (!onChange) return;
      const currentConfig = normalizeConfig(baseValue);
      const base =
        mode === "create"
          ? {
              ...configFromSettings(nextSettings),
              name: currentConfig.name,
              tool_set_preset: currentConfig.tool_set_preset,
              custom_tools: currentConfig.custom_tools,
            }
          : currentConfig;
      onChange(normalizeConfig({ ...base, ...partial }));
    },
    [mode, onChange, value],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [skillsRes, settingsRes, toolPresetsRes] = await Promise.all([
        fetch("/api/skills"),
        fetch("/api/settings/session-defaults"),
        fetch("/api/tool-presets"),
      ]);
      if (!skillsRes.ok) throw new Error(`Skills returned ${skillsRes.status}`);
      if (!settingsRes.ok) {
        throw new Error(`Settings returned ${settingsRes.status}`);
      }
      if (!toolPresetsRes.ok) {
        throw new Error(`Tool presets returned ${toolPresetsRes.status}`);
      }
      const skillsData: { skills?: SkillInfoResponse[] } =
        await skillsRes.json();
      const toolsData: ToolPresetListResponse = await toolPresetsRes.json();
      let settingsData: SessionSettings = normalizeSettings(
        await settingsRes.json(),
      );
      if (readonlyRef.current) {
        const currentConfig = normalizeConfig(valueRef.current);
        const currentRules = new Set(currentConfig.rules || []);
        settingsData = normalizeSettings({
          ...settingsData,
          preamble: currentConfig.preamble || settingsData.preamble,
          default_rule_ids: settingsData.rules
            .filter((rule) => currentRules.has(rule.content))
            .map((rule) => rule.id),
          default_skill_names:
            currentConfig.preloaded_skills?.length
              ? currentConfig.preloaded_skills
              : settingsData.default_skill_names,
        });
      }
      const skillItems = skillsData.skills || [];
      const toolItems = toolsData.tools || [];
      setSkills(skillItems);
      setTools(toolItems);
      setToolPresets(toolsData.presets || []);
      setActiveSkill((current) => current || skillItems[0]?.name || "");
      setActiveTool((current) => current || toolItems[0]?.name || "");
      setSettings(settingsData);
      if (
        !readonlyRef.current &&
        modeRef.current === "create" &&
        !appliedDefaultsRef.current
      ) {
        appliedDefaultsRef.current = true;
        const currentConfig = normalizeConfig(valueRef.current);
        onChangeRef.current?.(
          normalizeConfig({
            ...configFromSettings(settingsData),
            name: currentConfig.name,
            tool_set_preset: currentConfig.tool_set_preset,
            custom_tools: currentConfig.custom_tools,
          }),
        );
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveSettings = async (nextSettings: SessionSettings = settings) => {
    if (readonly) return;
    setSaving(true);
    try {
      const res = await fetch("/api/settings/session-defaults", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextSettings),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const saved = normalizeSettings(await res.json());
      setSettings(saved);
      if (mode === "create") emitCreateConfig(saved);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const patchSettings = (partial: Partial<SessionSettings>) => {
    if (readonly) return;
    const next = normalizeSettings({ ...settings, ...partial });
    setSettings(next);
    if (mode === "create") emitCreateConfig(next);
  };

  const toggleRule = (rule: SessionRule) => {
    if (readonly) return;
    const next = new Set(selectedRuleIds);
    if (next.has(rule.id)) next.delete(rule.id);
    else next.add(rule.id);
    patchSettings({ default_rule_ids: Array.from(next) });
  };

  const toggleSkill = (name: string) => {
    if (readonly) return;
    const next = new Set(selectedSkillNames);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    patchSettings({ default_skill_names: Array.from(next).sort() });
  };

  const setToolPreset = (preset: ToolSetPreset) => {
    if (readonly) return;
    const currentCustom = config.custom_tools || [];
    const nextCustom =
      preset === "custom"
        ? customToolDraft.length
          ? customToolDraft
          : currentCustom.length
            ? currentCustom
            : presetTools
        : currentCustom;
    if (preset === "custom") setCustomToolDraft(nextCustom);
    emitCreateConfig(settings, {
      tool_set_preset: preset,
      custom_tools: preset === "custom" ? nextCustom : [],
    });
  };

  const toggleCustomTool = (name: string) => {
    if (readonly || config.tool_set_preset !== "custom") return;
    const next = new Set(selectedToolNames);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    const ordered = tools
      .map((tool) => tool.name)
      .filter((toolName) => next.has(toolName));
    setCustomToolDraft(ordered);
    emitCreateConfig(settings, { custom_tools: ordered });
  };

  const addRule = async () => {
    if (readonly) return;
    const content = newRule.trim();
    if (!content) return;
    setSaving(true);
    try {
      const res = await fetch("/api/settings/session-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const saved = normalizeSettings(await res.json());
      setNewRule("");
      setSettings(saved);
      if (mode === "create") emitCreateConfig(saved);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const deleteRule = async (ruleId: string) => {
    if (readonly) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/settings/session-rules/${ruleId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const saved = normalizeSettings(await res.json());
      setSettings(saved);
      if (mode === "create") emitCreateConfig(saved);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const renderRules = () => (
    <>
      {!readonly && (
        <div className="session-rule-add">
          <textarea
            value={newRule}
            onChange={(e) => setNewRule(e.target.value)}
            placeholder="Add a reusable rule"
            rows={2}
          />
          <button
            type="button"
            onClick={() => void addRule()}
            disabled={saving || !newRule.trim()}
          >
            Add
          </button>
        </div>
      )}
      <div className="session-rule-list">
        {settings.rules.length === 0 && (
          <div className="session-customize-empty">No rules yet.</div>
        )}
        {settings.rules.map((rule) => (
          <div className="session-rule-row" key={rule.id}>
            <label>
              <input
                type="checkbox"
                checked={selectedRuleIds.has(rule.id)}
                disabled={readonly}
                onChange={() => toggleRule(rule)}
              />
              <span>{rule.content}</span>
            </label>
            {!readonly && (
              <button
                type="button"
                title="Delete rule"
                onClick={() => void deleteRule(rule.id)}
                disabled={saving}
              >
                <Icon name="trash" size={14} />
              </button>
            )}
          </div>
        ))}
      </div>
      {mode === "settings" && !readonly && (
        <div className="session-customize-actions">
          <button
            type="button"
            onClick={() => void saveSettings()}
            disabled={saving}
          >
            {saving ? "Saving" : "Save Default Rules"}
          </button>
        </div>
      )}
    </>
  );

  const renderSkills = () => (
    <div className="session-skills-layout">
      <aside className="session-skills-sidebar">
        {skills.length === 0 && (
          <div className="session-customize-empty">No skills available.</div>
        )}
        {skills.map((skill) => (
          <button
            type="button"
            className={`session-skill-nav ${activeSkillInfo?.name === skill.name ? "active" : ""}`}
            key={skill.name}
            onClick={() => setActiveSkill(skill.name)}
          >
            <input
              type="checkbox"
              checked={selectedSkillNames.has(skill.name)}
              disabled={readonly}
              onChange={(e) => {
                e.stopPropagation();
                toggleSkill(skill.name);
              }}
              onClick={(e) => e.stopPropagation()}
            />
            <span>{skill.name}</span>
          </button>
        ))}
      </aside>
      <section className="session-skill-preview">
        {activeSkillInfo ? (
          <>
            <h3>{activeSkillInfo.name}</h3>
            <p>{activeSkillInfo.description || "No description."}</p>
          </>
        ) : (
          <div className="session-customize-empty">Select a skill.</div>
        )}
      </section>
      {mode === "settings" && !readonly && (
        <div className="session-customize-actions session-customize-actions--wide">
          <button
            type="button"
            onClick={() => void saveSettings()}
            disabled={saving}
          >
            {saving ? "Saving" : "Save Default Skills"}
          </button>
        </div>
      )}
    </div>
  );

  const renderPreamble = () => (
    <>
      <label className="session-customize-field">
        <span>Preamble</span>
        <textarea
          value={mode === "create" ? config.preamble : settings.preamble}
          readOnly={readonly}
          onChange={(e) => {
            if (readonly) return;
            if (mode === "create") {
              emitCreateConfig(settings, { preamble: e.target.value });
            } else {
              patchSettings({ preamble: e.target.value });
            }
          }}
          placeholder="Optional system preamble for this session"
          rows={mode === "create" ? 4 : 8}
        />
      </label>
      {mode === "settings" && !readonly && (
        <div className="session-customize-actions">
          <button
            type="button"
            onClick={() => void saveSettings()}
            disabled={saving}
          >
            {saving ? "Saving" : "Save Default Preamble"}
          </button>
        </div>
      )}
    </>
  );

  const renderTools = () => {
    const shownTools =
      config.tool_set_preset === "custom"
        ? config.custom_tools || []
        : presetTools;
    return (
      <div className="session-tools">
        <label className="session-customize-field">
          <span>Tool Preset</span>
          <select
            value={config.tool_set_preset || "all"}
            disabled={readonly}
            onChange={(e) => setToolPreset(e.target.value as ToolSetPreset)}
          >
            {toolPresets.map((preset) => (
              <option key={preset.name} value={preset.name}>
                {toolPresetLabel(preset.name)}
              </option>
            ))}
            <option value="custom">{toolPresetLabel("custom")}</option>
          </select>
        </label>

        {config.tool_set_preset === "custom" ? (
          <div className="session-tools-layout">
            <aside className="session-tools-sidebar">
              {tools.length === 0 && (
                <div className="session-customize-empty">
                  No tools available.
                </div>
              )}
              {tools.map((tool) => (
                <button
                  type="button"
                  className={`session-tool-nav ${activeToolInfo?.name === tool.name ? "active" : ""}`}
                  key={tool.name}
                  onClick={() => setActiveTool(tool.name)}
                >
                  <input
                    type="checkbox"
                    checked={selectedToolNames.has(tool.name)}
                    disabled={readonly}
                    onChange={(e) => {
                      e.stopPropagation();
                      toggleCustomTool(tool.name);
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                  <span>{tool.name}</span>
                </button>
              ))}
            </aside>
            <section className="session-tool-preview">
              {activeToolInfo ? (
                <>
                  <h3>{activeToolInfo.name}</h3>
                  <p>{activeToolInfo.description || "No description."}</p>
                </>
              ) : (
                <div className="session-customize-empty">Select a tool.</div>
              )}
            </section>
          </div>
        ) : (
          <div className="session-tool-chip-list">
            {shownTools.map((toolName) => (
              <span key={toolName}>{toolName}</span>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      className={`session-customize session-customize--${mode}${readonly ? " session-customize--readonly" : ""}`}
    >
      <div className="session-customize-head">
        <div>
          <div className="session-customize-title">
            {readonly
              ? "Session Personalization"
              : mode === "create"
                ? "Customize Session"
                : "Session Defaults"}
          </div>
          <div className="session-customize-subtitle">
            {readonly
              ? "Current personalization is read-only after the session starts."
              : mode === "create"
              ? "Choose stored rules, skills, tools, and preamble for the first turn."
              : "Manage reusable defaults for new sessions."}
          </div>
        </div>
        <button
          className="session-customize-link"
          type="button"
          onClick={() => void load()}
          disabled={loading}
        >
          {loading ? "Loading" : "Refresh"}
        </button>
      </div>

      {error && <div className="session-customize-error">{error}</div>}

      {mode === "create" && (
        <label className="session-customize-field">
          <span>Name</span>
          <input
            value={config.name}
            readOnly={readonly}
            onChange={(e) => emitCreateConfig(settings, { name: e.target.value })}
            placeholder="Optional session name"
          />
        </label>
      )}

      {(mode === "create" || section === "rules") && renderRules()}
      {(mode === "create" || section === "skills") && renderSkills()}
      {mode === "create" && renderTools()}
      {(mode === "create" || section === "preamble") && renderPreamble()}
    </div>
  );
}
