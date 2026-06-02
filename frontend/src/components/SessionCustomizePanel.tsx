import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon";
import type {
  CreateSessionRequest,
  SessionRule,
  SessionSettings,
  SkillInfoResponse,
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

export default function SessionCustomizePanel({
  value,
  onChange,
  mode = "create",
  section = "rules",
  readonly = false,
}: SessionCustomizePanelProps) {
  const [settings, setSettings] = useState<SessionSettings>(emptySettings);
  const [skills, setSkills] = useState<SkillInfoResponse[]>([]);
  const [activeSkill, setActiveSkill] = useState("");
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
          ? { ...configFromSettings(nextSettings), name: currentConfig.name }
          : currentConfig;
      onChange(normalizeConfig({ ...base, ...partial }));
    },
    [mode, onChange, value],
  );

  const load = useCallback(async () => {
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
      const skillsData: { skills?: SkillInfoResponse[] } =
        await skillsRes.json();
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
      setSkills(skillItems);
      setActiveSkill((current) => current || skillItems[0]?.name || "");
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
              ? "Choose stored rules, skills, and preamble for the first turn."
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
      {(mode === "create" || section === "preamble") && renderPreamble()}
    </div>
  );
}
