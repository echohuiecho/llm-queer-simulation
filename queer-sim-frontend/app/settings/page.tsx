"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import FileUpload from "../../components/FileUpload";

interface AgentProfile {
  name: string;
  persona: string;
  name_en?: string;
  name_zh_Hans?: string;
  name_zh_Hant?: string;
  persona_en?: string;
  persona_zh_Hans?: string;
  persona_zh_Hant?: string;
}

interface InitialMessage {
  sender: string;
  text: string;
}

interface Settings {
  ollama_base: string;
  chat_model: string;
  embed_model: string;
  agent_profiles: Record<string, AgentProfile>;
  system_prompt: string;
  initial_messages: InitialMessage[];
  rag_directory: string;
  language?: string;
  system_prompt_en?: string;
  system_prompt_zh_Hans?: string;
  system_prompt_zh_Hant?: string;
  initial_messages_en?: InitialMessage[];
  initial_messages_zh_Hans?: InitialMessage[];
  initial_messages_zh_Hant?: InitialMessage[];
  storyline_context_dir?: string;
  storyline_context_content?: string;
}

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [ragDirs, setRagDirs] = useState<string[]>([]);
  const [newDirName, setNewDirName] = useState("");
  const [startConversationStatus, setStartConversationStatus] = useState<string | null>(null);
  const [youtubeUrls, setYoutubeUrls] = useState("");
  const [youtubeJobId, setYoutubeJobId] = useState<string | null>(null);
  const [youtubeJobStatus, setYoutubeJobStatus] = useState<any>(null);
  const [currentLanguage, setCurrentLanguage] = useState<string>("en");
  const [storylines, setStorylines] = useState<string[]>([]);
  const [selectedStoryline, setSelectedStoryline] = useState<string>("");

  useEffect(() => {
    fetchSettings();
    fetchRagDirs();
    fetchStorylines();
  }, []);

  const fetchStorylines = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/storylines");
      const data = await response.json();
      setStorylines(data.storylines || []);
      setSelectedStoryline(data.current || "");
    } catch (error) {
      console.error("Failed to fetch storylines:", error);
    }
  };

  const selectStoryline = async (name: string) => {
    try {
      const response = await fetch("http://localhost:8000/api/storylines/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (response.ok) {
        const data = await response.json();
        setSelectedStoryline(data.current || "");
        setSettings(prev => prev ? {
          ...prev,
          storyline_context_dir: data.current || "",
          storyline_context_content: data.content || ""
        } : null);
      }
    } catch (error) {
      console.error("Failed to select storyline:", error);
    }
  };

  useEffect(() => {
    let interval: any;
    if (youtubeJobId) {
      interval = setInterval(fetchYoutubeJobStatus, 2000);
    }
    return () => clearInterval(interval);
  }, [youtubeJobId]);

  const fetchYoutubeJobStatus = async () => {
    if (!youtubeJobId) return;
    try {
      const response = await fetch(`http://localhost:8000/api/rag/youtube/jobs/${youtubeJobId}`);
      const data = await response.json();
      setYoutubeJobStatus(data);
      if (data.status === "completed" || data.status === "failed") {
        setYoutubeJobId(null);
        if (data.status === "completed") {
          fetchRagDirs(); // Refresh list just in case
        }
      }
    } catch (error) {
      console.error("Failed to fetch YouTube job status:", error);
    }
  };

  const handleYoutubeIngest = async () => {
    if (!youtubeUrls.trim() || !settings?.rag_directory) return;
    const urls = youtubeUrls.split("\n").map(u => u.trim()).filter(u => u);
    if (urls.length === 0) return;

    setYoutubeJobStatus({ status: "pending", progress: 0 });
    try {
      const response = await fetch("http://localhost:8000/api/rag/youtube/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dir_name: settings.rag_directory,
          urls: urls
        }),
      });
      const data = await response.json();
      if (data.job_id) {
        setYoutubeJobId(data.job_id);
      } else {
        setYoutubeJobStatus({ status: "failed", errors: [data.error || "Failed to start job"] });
      }
    } catch (error) {
      setYoutubeJobStatus({ status: "failed", errors: ["Network error starting job"] });
    }
  };

  const fetchSettings = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/settings");
      const data = await response.json();

      // Migration: Convert old format to language-specific format if needed
      if (data.system_prompt && (!data.system_prompt_en && !data.system_prompt_zh_Hans && !data.system_prompt_zh_Hant)) {
        data.system_prompt_en = data.system_prompt;
        data.system_prompt_zh_Hans = data.system_prompt_zh_Hans || "";
        data.system_prompt_zh_Hant = data.system_prompt_zh_Hant || "";
      }
      if (data.initial_messages && (!data.initial_messages_en && !data.initial_messages_zh_Hans && !data.initial_messages_zh_Hant)) {
        data.initial_messages_en = data.initial_messages;
        data.initial_messages_zh_Hans = data.initial_messages_zh_Hans || [];
        data.initial_messages_zh_Hant = data.initial_messages_zh_Hant || [];
      }

      // Set default language if not specified
      if (!data.language) {
        data.language = "en";
      }

      // Normalize language code
      const normalizedLang = (data.language || "en").replace(/-/g, "_");
      data.language = normalizedLang;

      // Load current language's data into display fields
      const langKeyPrompt = `system_prompt_${normalizedLang}` as keyof Settings;
      const langKeyMessages = `initial_messages_${normalizedLang}` as keyof Settings;

      if (data[langKeyPrompt] !== undefined) {
        data.system_prompt = data[langKeyPrompt] as string;
      }
      if (data[langKeyMessages] !== undefined) {
        data.initial_messages = data[langKeyMessages] as InitialMessage[];
      }

      // Load agent profiles for current language
      if (data.agent_profiles) {
        for (const agentId in data.agent_profiles) {
          const profile = data.agent_profiles[agentId];
          const langKeyName = `name_${normalizedLang}` as keyof AgentProfile;
          const langKeyPersona = `persona_${normalizedLang}` as keyof AgentProfile;

          const langName = (profile[langKeyName] as string | undefined);
          const langPersona = (profile[langKeyPersona] as string | undefined);

          if (langName !== undefined) {
            profile.name = langName;
          } else if (normalizedLang !== "en" && profile.name_en) {
            profile.name = profile.name_en;
          }

          if (langPersona !== undefined) {
            profile.persona = langPersona;
          } else if (normalizedLang !== "en" && profile.persona_en) {
            profile.persona = profile.persona_en;
          }
        }
      }

      setSettings(data);
      setCurrentLanguage(normalizedLang);

      // Set selected storyline if available
      if (data.storyline_context_dir) {
        setSelectedStoryline(data.storyline_context_dir);
      }
    } catch (error) {
      console.error("Failed to fetch settings:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const fetchRagDirs = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/rag/directories");
      const data = await response.json();
      setRagDirs(data.directories);
    } catch (error) {
      console.error("Failed to fetch RAG directories:", error);
    }
  };

  const handleSave = async () => {
    if (!settings) return;
    setSaveStatus("Saving...");
    try {
      // Ensure language field is set
      const settingsToSave = {
        ...settings,
        language: currentLanguage,
      };

      const response = await fetch("http://localhost:8000/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settingsToSave),
      });
      if (response.ok) {
        setSaveStatus("Settings saved!");
        setTimeout(() => setSaveStatus(null), 3000);
        // Persistence to localStorage as well
        localStorage.setItem("queer_sim_settings", JSON.stringify(settingsToSave));
      } else {
        setSaveStatus("Failed to save settings");
      }
    } catch (error) {
      setSaveStatus("Error saving settings");
    }
  };

  const handleLanguageChange = (lang: string) => {
    if (!settings) return;

    // Normalize language code (convert zh-Hans/zh-Hant to zh_Hans/zh_Hant for consistency)
    const normalizedLang = lang.replace(/-/g, "_");
    const normalizedCurrentLang = currentLanguage.replace(/-/g, "_");

    // Save current language's data before switching
    const langKeyPrompt = `system_prompt_${normalizedCurrentLang}` as keyof Settings;
    const langKeyMessages = `initial_messages_${normalizedCurrentLang}` as keyof Settings;

    const updatedSettings: Settings = {
      ...settings,
      [langKeyPrompt]: settings.system_prompt,
      [langKeyMessages]: settings.initial_messages,
      language: normalizedLang,
    };

    // Load new language's data
    const newLangKeyPrompt = `system_prompt_${normalizedLang}` as keyof Settings;
    const newLangKeyMessages = `initial_messages_${normalizedLang}` as keyof Settings;

    const newPrompt = (updatedSettings[newLangKeyPrompt] as string | undefined);
    const newMessages = (updatedSettings[newLangKeyMessages] as InitialMessage[] | undefined);

    updatedSettings.system_prompt = newPrompt !== undefined ? newPrompt : "";
    updatedSettings.initial_messages = newMessages !== undefined ? newMessages : [];

    // Update agent profiles for new language
    if (updatedSettings.agent_profiles) {
      for (const agentId in updatedSettings.agent_profiles) {
        const profile = updatedSettings.agent_profiles[agentId];
        const newLangKeyName = `name_${normalizedLang}` as keyof AgentProfile;
        const newLangKeyPersona = `persona_${normalizedLang}` as keyof AgentProfile;

        const newName = (profile[newLangKeyName] as string | undefined);
        const newPersona = (profile[newLangKeyPersona] as string | undefined);

        if (newName !== undefined) {
          profile.name = newName;
        } else if (normalizedLang !== "en" && profile.name_en) {
          profile.name = profile.name_en;
        }

        if (newPersona !== undefined) {
          profile.persona = newPersona;
        } else if (normalizedLang !== "en" && profile.persona_en) {
          profile.persona = profile.persona_en;
        }
      }
    }

    setSettings(updatedSettings);
    setCurrentLanguage(normalizedLang);
  };

  const updateAgentName = (id: string, name: string) => {
    if (!settings) return;
    const langKeyName = `name_${currentLanguage}` as keyof AgentProfile;
    setSettings({
      ...settings,
      agent_profiles: {
        ...settings.agent_profiles,
        [id]: {
          ...settings.agent_profiles[id],
          name,
          [langKeyName]: name
        },
      },
    });
  };

  const updateAgentPersona = (id: string, persona: string) => {
    if (!settings) return;
    const langKeyPersona = `persona_${currentLanguage}` as keyof AgentProfile;
    setSettings({
      ...settings,
      agent_profiles: {
        ...settings.agent_profiles,
        [id]: {
          ...settings.agent_profiles[id],
          persona,
          [langKeyPersona]: persona
        },
      },
    });
  };

  const updateInitialMessage = (index: number, field: keyof InitialMessage, value: string) => {
    if (!settings) return;
    const newMessages = [...settings.initial_messages];
    newMessages[index] = { ...newMessages[index], [field]: value };
    const langKeyMessages = `initial_messages_${currentLanguage}` as keyof Settings;
    setSettings({
      ...settings,
      initial_messages: newMessages,
      [langKeyMessages]: newMessages
    });
  };

  const addInitialMessage = () => {
    if (!settings) return;
    const newMessages = [...settings.initial_messages, { sender: "", text: "" }];
    const langKeyMessages = `initial_messages_${currentLanguage}` as keyof Settings;
    setSettings({
      ...settings,
      initial_messages: newMessages,
      [langKeyMessages]: newMessages
    });
  };

  const removeInitialMessage = (index: number) => {
    if (!settings) return;
    const newMessages = settings.initial_messages.filter((_, i) => i !== index);
    const langKeyMessages = `initial_messages_${currentLanguage}` as keyof Settings;
    setSettings({
      ...settings,
      initial_messages: newMessages,
      [langKeyMessages]: newMessages
    });
  };

  const createRagDir = async () => {
    if (!newDirName.trim()) return;
    try {
      const response = await fetch("http://localhost:8000/api/rag/directories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newDirName.trim() }),
      });
      if (response.ok) {
        fetchRagDirs();
        setNewDirName("");
      }
    } catch (error) {
      console.error("Failed to create RAG directory:", error);
    }
  };

  const selectRagDir = async (name: string) => {
    try {
      const response = await fetch("http://localhost:8000/api/rag/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (response.ok) {
        setSettings(prev => prev ? { ...prev, rag_directory: name } : null);
      }
    } catch (error) {
      console.error("Failed to select RAG directory:", error);
    }
  };

  const startConversationWithKb = async (name?: string) => {
    const kbName = name || settings?.rag_directory;
    if (!kbName) {
      setStartConversationStatus("Please select a knowledge base first");
      setTimeout(() => setStartConversationStatus(null), 3000);
      return;
    }

    setStartConversationStatus("Starting conversation...");
    try {
      // Ensure storyline selection is saved before starting conversation
      if (selectedStoryline) {
        await selectStoryline(selectedStoryline);
      }

      const response = await fetch("http://localhost:8000/api/rag/start-conversation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: kbName }),
      });
      if (response.ok) {
        setStartConversationStatus("Conversation started! Redirecting...");
        // Update settings to reflect the selected KB
        setSettings(prev => prev ? { ...prev, rag_directory: kbName } : null);
        // Navigate back to main page after a short delay
        setTimeout(() => {
          router.push("/");
        }, 1500);
      } else {
        const error = await response.json();
        setStartConversationStatus(`Failed: ${error.error || "Unknown error"}`);
        setTimeout(() => setStartConversationStatus(null), 3000);
      }
    } catch (error) {
      setStartConversationStatus("Error starting conversation");
      setTimeout(() => setStartConversationStatus(null), 3000);
    }
  };

  if (isLoading) return <div style={{ padding: 40, color: "white" }}>Loading...</div>;
  if (!settings) return <div style={{ padding: 40, color: "white" }}>Error loading settings</div>;

  return (
    <main style={{ minHeight: "100vh", background: "#050505", color: "white", padding: "40px 20px" }}>
      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 40 }}>
          <h1 style={{ fontSize: 32, fontWeight: 700 }}>Settings</h1>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <Link
              href="/"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: "rgba(255,255,255,0.05)",
                color: "white",
                textDecoration: "none",
                fontSize: 14
              }}
            >
              Back to World
            </Link>
            <button
              onClick={handleSave}
              style={{
                padding: "8px 24px",
                borderRadius: 8,
                background: "#4a9eff",
                color: "white",
                fontWeight: 600,
                border: "none",
                cursor: "pointer",
                fontSize: 14
              }}
            >
              {saveStatus || "Save Changes"}
            </button>
          </div>
        </div>

        {/* Language Selection Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>Language</h2>
          <div style={{ padding: 20, borderRadius: 16, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
            <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Select Language</label>
            <select
              value={currentLanguage}
              onChange={(e) => handleLanguageChange(e.target.value)}
              style={{
                width: "100%",
                padding: 10,
                background: "#111",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8,
                color: "white",
                fontSize: 14
              }}
            >
              <option value="en">English</option>
              <option value="zh_Hans">中文 (简体) / Chinese (Simplified)</option>
              <option value="zh_Hant">中文 (繁體) / Chinese (Traditional)</option>
            </select>
            <div style={{ marginTop: 12, fontSize: 12, opacity: 0.6 }}>
              Current language: {currentLanguage === "en" ? "English" : currentLanguage === "zh_Hans" ? "中文 (简体)" : "中文 (繁體)"}
            </div>
          </div>
        </section>

        {/* Characters Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>Character Configuration ({currentLanguage === "en" ? "English" : currentLanguage === "zh_Hans" ? "中文 (简体)" : "中文 (繁體)"})</h2>
          {Object.entries(settings.agent_profiles).map(([id, profile]) => (
            <div key={id} style={{ marginBottom: 24, padding: 20, borderRadius: 16, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Name ({id})</label>
                <input
                  value={profile.name}
                  onChange={(e) => updateAgentName(id, e.target.value)}
                  style={{ width: "100%", padding: 10, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white" }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Persona</label>
                <textarea
                  value={profile.persona}
                  onChange={(e) => updateAgentPersona(id, e.target.value)}
                  rows={4}
                  style={{ width: "100%", padding: 10, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white", fontSize: 13 }}
                />
              </div>
            </div>
          ))}
        </section>

        {/* System Prompt Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>System Prompt ({currentLanguage === "en" ? "English" : currentLanguage === "zh_Hans" ? "中文 (简体)" : "中文 (繁體)"})</h2>
          <textarea
            value={settings.system_prompt}
            onChange={(e) => {
              const langKeyPrompt = `system_prompt_${currentLanguage}` as keyof Settings;
              setSettings({
                ...settings,
                system_prompt: e.target.value,
                [langKeyPrompt]: e.target.value
              });
            }}
            rows={6}
            style={{ width: "100%", padding: 20, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 16, color: "white", fontSize: 14, lineHeight: 1.6 }}
          />
        </section>

        {/* Initial Messages Section */}
        <section style={{ marginBottom: 48 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <h2 style={{ fontSize: 20, fontWeight: 600, opacity: 0.8 }}>Initial Messages ({currentLanguage === "en" ? "English" : currentLanguage === "zh_Hans" ? "中文 (简体)" : "中文 (繁體)"})</h2>
            <button
              onClick={addInitialMessage}
              style={{ background: "none", border: "1px solid #4a9eff", color: "#4a9eff", borderRadius: 6, padding: "4px 12px", fontSize: 12, cursor: "pointer" }}
            >
              + Add Message
            </button>
          </div>
          {settings.initial_messages.map((msg, idx) => (
            <div key={idx} style={{ display: "flex", gap: 12, marginBottom: 12 }}>
              <input
                value={msg.sender}
                placeholder="Sender"
                onChange={(e) => updateInitialMessage(idx, "sender", e.target.value)}
                style={{ width: 140, padding: "8px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white", fontSize: 13 }}
              />
              <input
                value={msg.text}
                placeholder="Message text"
                onChange={(e) => updateInitialMessage(idx, "text", e.target.value)}
                style={{ flex: 1, padding: "8px 12px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white", fontSize: 13 }}
              />
              <button
                onClick={() => removeInitialMessage(idx)}
                style={{ background: "rgba(255,74,74,0.1)", border: "none", color: "#ff4a4a", borderRadius: 8, width: 36, height: 36, cursor: "pointer" }}
              >
                ×
              </button>
            </div>
          ))}
        </section>

        {/* Storyline Context Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>Storyline Context</h2>
          <div style={{ padding: 24, borderRadius: 16, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Select Storyline</label>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}>
                  <select
                    value={selectedStoryline}
                    onChange={(e) => selectStoryline(e.target.value)}
                    style={{ width: "100%", padding: 10, background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white" }}
                  >
                    <option value="">None (Use fixed initial messages)</option>
                    {storylines.map(storyline => (
                      <option key={storyline} value={storyline}>{storyline}</option>
                    ))}
                  </select>
                </div>
              </div>
              {selectedStoryline && (
                <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
                  Selected: <strong>{selectedStoryline}</strong>. Initial messages will be dynamically generated based on this storyline's context.
                </div>
              )}
              {!selectedStoryline && (
                <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
                  No storyline selected. Using fixed initial messages from settings.
                </div>
              )}
            </div>
          </div>
        </section>

        {/* RAG Data Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>RAG Data Directory</h2>
          <div style={{ padding: 24, borderRadius: 16, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.05)" }}>
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Select Directory</label>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <div style={{ flex: 1 }}>
                  <select
                    value={settings.rag_directory}
                    onChange={(e) => selectRagDir(e.target.value)}
                    style={{ width: "100%", padding: 10, background: "#111", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white" }}
                  >
                    {ragDirs.map(dir => (
                      <option key={dir} value={dir}>{dir}</option>
                    ))}
                  </select>
                </div>
                <button
                  onClick={() => startConversationWithKb()}
                  disabled={!!startConversationStatus}
                  style={{
                    padding: "10px 20px",
                    background: startConversationStatus ? "rgba(74, 158, 255, 0.5)" : "#4a9eff",
                    color: "white",
                    border: "none",
                    borderRadius: 8,
                    cursor: startConversationStatus ? "not-allowed" : "pointer",
                    fontWeight: 600,
                    fontSize: 14,
                    whiteSpace: "nowrap"
                  }}
                >
                  {startConversationStatus || "Start Conversation"}
                </button>
              </div>
              {startConversationStatus && startConversationStatus !== "Starting conversation..." && startConversationStatus !== "Conversation started! Redirecting..." && (
                <div style={{ marginTop: 8, fontSize: 12, color: "#ff4a4a" }}>
                  {startConversationStatus}
                </div>
              )}
              {startConversationStatus === "Conversation started! Redirecting..." && (
                <div style={{ marginTop: 8, fontSize: 12, color: "#4a9eff" }}>
                  {startConversationStatus}
                </div>
              )}
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Create New Directory</label>
              <div style={{ display: "flex", gap: 12 }}>
                <input
                  value={newDirName}
                  onChange={(e) => setNewDirName(e.target.value)}
                  placeholder="Directory name"
                  style={{ flex: 1, padding: 10, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white" }}
                />
                <button
                  onClick={createRagDir}
                  style={{ padding: "0 16px", background: "#4a9eff", color: "white", border: "none", borderRadius: 8, cursor: "pointer" }}
                >
                  Create
                </button>
              </div>
            </div>

            <div>
              <label style={{ display: "block", fontSize: 12, opacity: 0.5, marginBottom: 8 }}>Upload Files to `{settings.rag_directory}`</label>
              <FileUpload
                currentDir={settings.rag_directory}
                onUploadComplete={(filename) => {
                  console.log(`Uploaded ${filename}`);
                  // Maybe show a temporary success message
                }}
              />
            </div>

            <div style={{ marginTop: 32, paddingTop: 32, borderTop: "1px solid rgba(255,255,255,0.05)" }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>YouTube Ingestion</h3>
              <p style={{ fontSize: 13, opacity: 0.7, marginBottom: 16 }}>
                Enter YouTube URLs (one per line) to download video, transcript, and extract frames as RAG context.
              </p>
              <textarea
                value={youtubeUrls}
                onChange={(e) => setYoutubeUrls(e.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                rows={3}
                style={{ width: "100%", padding: 12, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, color: "white", fontSize: 13, marginBottom: 12 }}
                disabled={!!youtubeJobId}
              />
              <button
                onClick={handleYoutubeIngest}
                disabled={!!youtubeJobId || !youtubeUrls.trim()}
                style={{
                  padding: "10px 24px",
                  background: youtubeJobId || !youtubeUrls.trim() ? "rgba(74, 158, 255, 0.5)" : "#4a9eff",
                  color: "white",
                  border: "none",
                  borderRadius: 8,
                  cursor: youtubeJobId || !youtubeUrls.trim() ? "not-allowed" : "pointer",
                  fontWeight: 600,
                  fontSize: 14
                }}
              >
                {youtubeJobId ? "Ingesting..." : "Start Ingestion"}
              </button>

              {youtubeJobStatus && (
                <div style={{ marginTop: 20, padding: 16, borderRadius: 12, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase" }}>Status: {youtubeJobStatus.status}</span>
                    <span style={{ fontSize: 12 }}>{Math.round(youtubeJobStatus.progress)}%</span>
                  </div>
                  <div style={{ width: "100%", height: 4, background: "rgba(255,255,255,0.1)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${youtubeJobStatus.progress}%`, height: "100%", background: "#4a9eff", transition: "width 0.3s ease" }} />
                  </div>
                  {youtubeJobStatus.current_url && (
                    <div style={{ marginTop: 8, fontSize: 11, opacity: 0.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      Processing: {youtubeJobStatus.current_url}
                    </div>
                  )}
                  {youtubeJobStatus.errors && youtubeJobStatus.errors.length > 0 && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 11, color: "#ff4a4a", fontWeight: 600, marginBottom: 4 }}>Errors:</div>
                      {youtubeJobStatus.errors.map((err: string, i: number) => (
                        <div key={i} style={{ fontSize: 11, color: "#ff4a4a", marginBottom: 2 }}>• {err}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>

        <div style={{ padding: "40px 0", borderTop: "1px solid rgba(255,255,255,0.1)", textAlign: "center" }}>
          <button
            onClick={handleSave}
            style={{
              padding: "12px 48px",
              borderRadius: 12,
              background: "#4a9eff",
              color: "white",
              fontWeight: 700,
              border: "none",
              cursor: "pointer",
              fontSize: 16
            }}
          >
            {saveStatus || "Save All Settings"}
          </button>
        </div>
      </div>
    </main>
  );
}
