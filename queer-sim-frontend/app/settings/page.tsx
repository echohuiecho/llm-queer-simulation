"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import FileUpload from "../../components/FileUpload";

interface AgentProfile {
  name: string;
  persona: string;
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
}

export default function SettingsPage() {
  const router = useRouter();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [ragDirs, setRagDirs] = useState<string[]>([]);
  const [newDirName, setNewDirName] = useState("");
  const [startConversationStatus, setStartConversationStatus] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
    fetchRagDirs();
  }, []);

  const fetchSettings = async () => {
    try {
      const response = await fetch("http://localhost:8000/api/settings");
      const data = await response.json();
      setSettings(data);
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
      const response = await fetch("http://localhost:8000/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (response.ok) {
        setSaveStatus("Settings saved!");
        setTimeout(() => setSaveStatus(null), 3000);
        // Persistence to localStorage as well
        localStorage.setItem("queer_sim_settings", JSON.stringify(settings));
      } else {
        setSaveStatus("Failed to save settings");
      }
    } catch (error) {
      setSaveStatus("Error saving settings");
    }
  };

  const updateAgentName = (id: string, name: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      agent_profiles: {
        ...settings.agent_profiles,
        [id]: { ...settings.agent_profiles[id], name },
      },
    });
  };

  const updateAgentPersona = (id: string, persona: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      agent_profiles: {
        ...settings.agent_profiles,
        [id]: { ...settings.agent_profiles[id], persona },
      },
    });
  };

  const updateInitialMessage = (index: number, field: keyof InitialMessage, value: string) => {
    if (!settings) return;
    const newMessages = [...settings.initial_messages];
    newMessages[index] = { ...newMessages[index], [field]: value };
    setSettings({ ...settings, initial_messages: newMessages });
  };

  const addInitialMessage = () => {
    if (!settings) return;
    setSettings({
      ...settings,
      initial_messages: [...settings.initial_messages, { sender: "", text: "" }],
    });
  };

  const removeInitialMessage = (index: number) => {
    if (!settings) return;
    const newMessages = settings.initial_messages.filter((_, i) => i !== index);
    setSettings({ ...settings, initial_messages: newMessages });
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

        {/* Characters Section */}
        <section style={{ marginBottom: 48 }}>
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>Character Configuration</h2>
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
          <h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20, opacity: 0.8 }}>System Prompt</h2>
          <textarea
            value={settings.system_prompt}
            onChange={(e) => setSettings({ ...settings, system_prompt: e.target.value })}
            rows={6}
            style={{ width: "100%", padding: 20, background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 16, color: "white", fontSize: 14, lineHeight: 1.6 }}
          />
        </section>

        {/* Initial Messages Section */}
        <section style={{ marginBottom: 48 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <h2 style={{ fontSize: 20, fontWeight: 600, opacity: 0.8 }}>Initial Messages</h2>
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
