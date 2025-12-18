"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

type RoomId = "apartment" | "cafe" | "group_chat";

type Msg = { type: "message"; room: string; from: string; text: string; ts: number };
type PresenceEvent = { type: "presence"; agent: string; room: string; pos: { x: number; y: number }; ts: number };
type SystemMsg = { type: "system_message"; room: string; text: string; ts: number };
type AgentStateMsg = { type: "agent_state"; id: string; name: string; room: RoomId; pos: { x: number; y: number }; ts: number };

type StateMsg = {
  type: "state";
  rooms: string[];
  agents: { id: string; name: string; room: RoomId; pos: { x: number; y: number } }[];
  history: Record<string, (Msg | SystemMsg)[]>;
};

type Event = {
  id: string;
  type: "message" | "presence" | "system" | "connection";
  text: string;
  ts: number;
  room?: string;
  agent?: string;
};

const ROOM_LABEL: Record<RoomId, string> = {
  apartment: "Apartment",
  cafe: "Cafe",
  group_chat: "Group Chat",
};

const DOOR_POS: Record<RoomId, { x: number; y: number }> = {
  apartment: { x: 0.92, y: 0.55 },  // right edge-ish
  cafe: { x: 0.10, y: 0.85 },       // bottom-left-ish
  group_chat: { x: 0.10, y: 0.15 }, // top-left-ish
};

function AvatarChip({ name, pos, isActive, icon, onClick }: { name: string; pos: { x: number; y: number }; isActive: boolean; icon: string | null; onClick?: () => void }) {
  return (
    <div
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      style={{
        position: "absolute",
        left: `${pos.x * 100}%`,
        top: `${pos.y * 100}%`,
        transform: "translate(-50%, -50%)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 4,
        zIndex: 10,
        transition: "all 0.8s cubic-bezier(0.4, 0, 0.2, 1)",
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: "50%",
          border: isActive ? "2px solid #4a9eff" : "2px solid rgba(255,255,255,0.3)",
          boxShadow: isActive ? "0 0 10px rgba(74, 158, 255, 0.5)" : "none",
          overflow: "hidden",
          background: "#222",
          transition: "all 0.2s ease",
        }}
        onMouseEnter={(e) => {
          if (onClick) {
            e.currentTarget.style.transform = "scale(1.1)";
            e.currentTarget.style.boxShadow = "0 0 15px rgba(74, 158, 255, 0.6)";
          }
        }}
        onMouseLeave={(e) => {
          if (onClick) {
            e.currentTarget.style.transform = "scale(1)";
            e.currentTarget.style.boxShadow = isActive ? "0 0 10px rgba(74, 158, 255, 0.5)" : "none";
          }
        }}
      >
        {icon ? (
          <img src={icon} alt={name} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>
            {name.charAt(0)}
          </div>
        )}
      </div>
      <div
        style={{
          padding: "2px 8px",
          borderRadius: 999,
          background: "rgba(0,0,0,0.6)",
          backdropFilter: "blur(4px)",
          border: "1px solid rgba(255,255,255,0.18)",
          fontSize: 12,
          color: "white",
          whiteSpace: "nowrap",
        }}
      >
        {name}
      </div>
    </div>
  );
}

function RoomContainer({
  id,
  active,
  onEnter,
  children,
}: {
  id: RoomId;
  active: boolean;
  onEnter: (id: RoomId) => void;
  children?: React.ReactNode;
}) {
  return (
    <div
      onClick={() => onEnter(id)}
      style={{
        position: "relative",
        borderRadius: 24,
        border: active ? "3px solid #4a9eff" : "2px solid rgba(255,255,255,0.1)",
        overflow: "hidden",
        cursor: "pointer",
        transition: "all 0.3s ease",
        height: "100%",
        boxShadow: active ? "0 0 20px rgba(74, 158, 255, 0.2)" : "none",
        background:
          id === "apartment"
            ? "radial-gradient(circle at 30% 30%, rgba(100,255,200,0.08), rgba(0,0,0,0.8))"
            : id === "cafe"
            ? "radial-gradient(circle at 70% 30%, rgba(255,220,140,0.08), rgba(0,0,0,0.8))"
            : "radial-gradient(circle at 50% 50%, rgba(140,180,255,0.08), rgba(0,0,0,0.8))",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 16,
          top: 16,
          padding: "4px 12px",
          borderRadius: 999,
          background: active ? "rgba(74, 158, 255, 0.2)" : "rgba(255,255,255,0.05)",
          border: `1px solid ${active ? "#4a9eff" : "rgba(255,255,255,0.1)"}`,
          fontSize: 14,
          fontWeight: 600,
          color: active ? "#4a9eff" : "rgba(255,255,255,0.6)",
          zIndex: 5,
        }}
      >
        {ROOM_LABEL[id]}
      </div>

      <div
        style={{
          position: "absolute",
          left: `${DOOR_POS[id].x * 100}%`,
          top: `${DOOR_POS[id].y * 100}%`,
          width: 24,
          height: 8,
          transform: "translate(-50%, -50%)",
          borderRadius: 4,
          background: "rgba(255,255,255,0.1)",
          border: "1px solid rgba(255,255,255,0.2)",
        }}
      />

      {children}
    </div>
  );
}

export default function Home() {
  const [wsReady, setWsReady] = useState(false);
  const [wsError, setWsError] = useState<string | null>(null);
  const [rooms, setRooms] = useState<string[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; room: RoomId; pos: { x: number; y: number } }[]>([]);
  const [activeRoom, setActiveRoom] = useState<RoomId>("group_chat");
  const [messages, setMessages] = useState<Record<string, (Msg | SystemMsg)[]>>({});
  const [events, setEvents] = useState<Event[]>([]);
  const [input, setInput] = useState("");
  const [dmOpen, setDmOpen] = useState<string | null>(null); // Agent name for open DM
  const [dmMessages, setDmMessages] = useState<Record<string, (Msg | SystemMsg)[]>>({}); // DM conversations keyed by agent name
  const [dmInput, setDmInput] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const eventIdCounter = useRef(0);
  const [agentProfiles, setAgentProfiles] = useState<Record<string, {name: string}>>({});

  useEffect(() => {
    fetch("http://localhost:8000/api/settings")
      .then(res => res.json())
      .then(data => {
        setAgentProfiles(data.agent_profiles);
      })
      .catch(err => console.error("Failed to fetch settings", err));
  }, []);

  const getAgentIcon = (name: string): string | null => {
    // Try to find if this name belongs to any of our known profiles
    // For now we map Noor, Ji-woo, Mika to their images regardless of full name
    if (name.includes("Noor")) return "/agents/Noor.jpg";
    if (name.includes("Ji-woo")) return "/agents/Ji-woo.jpg";
    if (name.includes("Mika")) return "/agents/Mika.jpg";
    return null;
  };

  const connect = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket("ws://localhost:8000/ws");
    wsRef.current = ws;

    ws.onopen = () => {
      setWsReady(true);
      setWsError(null);
      setEvents((prev) => [
        ...prev,
        { id: `evt-${eventIdCounter.current++}`, type: "connection", text: "Connected to world", ts: Date.now() / 1000 },
      ]);
    };

    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data);

      if (data.type === "state") {
        const s = data as StateMsg;
        setRooms(s.rooms);
        setAgents(s.agents as any);
        // Separate room messages from DM messages
        const roomMsgs: Record<string, (Msg | SystemMsg)[]> = {};
        const dmMsgs: Record<string, (Msg | SystemMsg)[]> = {};
        for (const [key, msgs] of Object.entries(s.history)) {
          if (key.startsWith("dm:")) {
            const agentName = key.replace("dm:", "");
            dmMsgs[agentName] = msgs as (Msg | SystemMsg)[];
          } else {
            roomMsgs[key] = msgs as (Msg | SystemMsg)[];
          }
        }
        setMessages(roomMsgs);
        setDmMessages(dmMsgs);
        return;
      }

      if (data.type === "message") {
        const m = data as Msg;
        // Check if this is a DM (room starts with "dm:")
        if (m.room.startsWith("dm:")) {
          const dmKey = m.room.replace("dm:", "");
          setDmMessages((prev) => ({
            ...prev,
            [dmKey]: [...(prev[dmKey] ?? []), m].slice(-200),
          }));
        } else {
          setMessages((prev) => ({
            ...prev,
            [m.room]: [...(prev[m.room] ?? []), m].slice(-200),
          }));
        }
        setEvents((prev) => [
          ...prev,
          { id: `evt-${eventIdCounter.current++}`, type: "message", text: `${m.from}: ${m.text}`, ts: m.ts, room: m.room },
        ]);
        return;
      }

      if (data.type === "presence") {
        const p = data as PresenceEvent;
        setAgents((prev) => {
          const agent = prev.find((a) => a.id === p.agent);
          const agentName = agent?.name || p.agent;
          const oldRoom = agent?.room as RoomId;

          if (oldRoom && oldRoom !== p.room) {
            setMessages((msgPrev) => ({
              ...msgPrev,
              [oldRoom]: [...(msgPrev[oldRoom] ?? []), { type: "system_message", room: oldRoom, text: `${agentName} left #${oldRoom}`, ts: p.ts } as any].slice(-200),
              [p.room]: [...(msgPrev[p.room] ?? []), { type: "system_message", room: p.room, text: `${agentName} joined #${p.room}`, ts: p.ts } as any].slice(-200),
            }));
          }

          return prev.map((a) => (a.id === p.agent ? { ...a, room: p.room as RoomId, pos: p.pos || a.pos } : a));
        });
      }

      if (data.type === "agent_state") {
        const s = data as AgentStateMsg;
        setAgents((prev) => prev.map((a) => (a.id === s.id ? { ...a, pos: s.pos, room: s.room } : a)));
      }
    };

    ws.onclose = () => {
      setWsReady(false);
      reconnectTimeoutRef.current = setTimeout(connect, 2000);
    };
  };

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, []);

  const roomMsgs = useMemo(() => (messages[activeRoom] ?? []) as (Msg | SystemMsg)[], [messages, activeRoom]);
  const currentDmMsgs = useMemo(() => (dmOpen ? (dmMessages[dmOpen] ?? []) : []) as (Msg | SystemMsg)[], [dmMessages, dmOpen]);

  const send = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !input.trim()) return;
    ws.send(JSON.stringify({ type: "user_message", room: activeRoom, text: input.trim() }));
    setInput("");
  };

  const sendDm = () => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !dmInput.trim() || !dmOpen) return;
    ws.send(JSON.stringify({ type: "user_dm", agent: dmOpen, text: dmInput.trim() }));
    setDmInput("");
  };

  return (
    <main style={{ height: "100vh", display: "grid", gridTemplateColumns: "1fr 400px", gap: 20, padding: 20, background: "#050505", color: "white", overflow: "hidden" }}>
      {/* Floorplan section */}
      <section style={{ display: "grid", gridTemplateColumns: "1fr 0.8fr", gridTemplateRows: "1fr 1fr", gap: 20 }}>
        <div style={{ gridRow: "1 / 3" }}>
          <RoomContainer id="apartment" active={activeRoom === "apartment"} onEnter={setActiveRoom}>
            {agents.filter(a => a.room === "apartment").map(a => (
              <AvatarChip key={a.id} name={a.name} pos={a.pos} isActive={activeRoom === "apartment"} icon={getAgentIcon(a.name)} onClick={() => setDmOpen(a.name)} />
            ))}
          </RoomContainer>
        </div>
        <div>
          <RoomContainer id="cafe" active={activeRoom === "cafe"} onEnter={setActiveRoom}>
            {agents.filter(a => a.room === "cafe").map(a => (
              <AvatarChip key={a.id} name={a.name} pos={a.pos} isActive={activeRoom === "cafe"} icon={getAgentIcon(a.name)} onClick={() => setDmOpen(a.name)} />
            ))}
          </RoomContainer>
        </div>
        <div>
          <RoomContainer id="group_chat" active={activeRoom === "group_chat"} onEnter={setActiveRoom}>
            {agents.filter(a => a.room === "group_chat").map(a => (
              <AvatarChip key={a.id} name={a.name} pos={a.pos} isActive={activeRoom === "group_chat"} icon={getAgentIcon(a.name)} onClick={() => setDmOpen(a.name)} />
            ))}
          </RoomContainer>
        </div>
      </section>

      {/* Chat section */}
      <aside style={{
        display: "flex",
        flexDirection: "column",
        background: "rgba(20, 20, 20, 0.6)",
        backdropFilter: "blur(20px)",
        borderRadius: 24,
        border: "1px solid rgba(255, 255, 255, 0.1)",
        overflow: "hidden"
      }}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid rgba(255, 255, 255, 0.1)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 13, opacity: 0.5, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>Current Room</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>#{activeRoom}</div>
          </div>
          <Link
            href="/settings"
            style={{
              padding: "8px 16px",
              borderRadius: 8,
              background: "rgba(255,255,255,0.05)",
              color: "white",
              textDecoration: "none",
              fontSize: 13,
              fontWeight: 600,
              border: "1px solid rgba(255,255,255,0.1)"
            }}
          >
            Settings
          </Link>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
          {roomMsgs.map((m, idx) => {
            if (m.type === "system_message") {
              return (
                <div key={idx} style={{ textAlign: "center", margin: "16px 0", opacity: 0.5, fontSize: 13, color: "#4a9eff" }}>
                  — {m.text} —
                </div>
              );
            }
            const isUser = m.from === "You";
            const icon = getAgentIcon(m.from);
            return (
              <div key={idx} style={{ marginBottom: 20, display: "flex", gap: 12, alignItems: "flex-start" }}>
                {!isUser && (
                  <div style={{ width: 32, height: 32, borderRadius: "50%", overflow: "hidden", background: "#333", flexShrink: 0 }}>
                    {icon ? <img src={icon} alt={m.from} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : m.from.charAt(0)}
                  </div>
                )}
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: isUser ? "#4a9eff" : "#888" }}>{m.from}</div>
                  <div style={{
                    background: isUser ? "#4a9eff" : "rgba(255,255,255,0.05)",
                    padding: "10px 14px",
                    borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
                    fontSize: 15,
                    lineHeight: 1.5,
                    color: isUser ? "white" : "rgba(255,255,255,0.9)"
                  }}>
                    {m.text}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ padding: 24, background: "rgba(0,0,0,0.2)", borderTop: "1px solid rgba(255,255,255,0.1)" }}>
          <div style={{ display: "flex", gap: 12 }}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={`Message #${activeRoom}...`}
              style={{
                flex: 1,
                padding: "14px 18px",
                borderRadius: 14,
                border: "1px solid rgba(255,255,255,0.1)",
                background: "rgba(255,255,255,0.05)",
                color: "white",
                outline: "none"
              }}
            />
            <button
              onClick={send}
              style={{
                padding: "0 24px",
                borderRadius: 14,
                background: "#4a9eff",
                color: "white",
                fontWeight: 600,
                border: "none",
                cursor: "pointer"
              }}
            >
              Send
            </button>
          </div>
        </div>
      </aside>

      {/* DM Drawer */}
      {dmOpen && (
        <div
          style={{
            position: "fixed",
            right: 0,
            top: 0,
            bottom: 0,
            width: 400,
            background: "rgba(20, 20, 20, 0.95)",
            backdropFilter: "blur(20px)",
            borderLeft: "1px solid rgba(255, 255, 255, 0.1)",
            display: "flex",
            flexDirection: "column",
            zIndex: 1000,
            boxShadow: "-4px 0 20px rgba(0, 0, 0, 0.5)",
            animation: "slideIn 0.3s ease-out",
          }}
        >
          <style>{`
            @keyframes slideIn {
              from {
                transform: translateX(100%);
              }
              to {
                transform: translateX(0);
              }
            }
          `}</style>

          {/* DM Header */}
          <div style={{ padding: "20px 24px", borderBottom: "1px solid rgba(255, 255, 255, 0.1)", display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={() => setDmOpen(null)}
              style={{
                width: 32,
                height: 32,
                borderRadius: "50%",
                border: "1px solid rgba(255, 255, 255, 0.2)",
                background: "rgba(255, 255, 255, 0.05)",
                color: "white",
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 18,
              }}
            >
              ×
            </button>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, opacity: 0.5, textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>Direct Message</div>
              <div style={{ fontSize: 20, fontWeight: 700, display: "flex", alignItems: "center", gap: 10 }}>
                {getAgentIcon(dmOpen) && (
                  <img
                    src={getAgentIcon(dmOpen)!}
                    alt={dmOpen}
                    style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }}
                  />
                )}
                {dmOpen}
              </div>
            </div>
          </div>

          {/* DM Messages */}
          <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
            {currentDmMsgs.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 20px", opacity: 0.5, fontSize: 14 }}>
                No messages yet. Start the conversation!
              </div>
            ) : (
              currentDmMsgs.map((m, idx) => {
                if (m.type === "system_message") {
                  return (
                    <div key={idx} style={{ textAlign: "center", margin: "16px 0", opacity: 0.5, fontSize: 13, color: "#4a9eff" }}>
                      — {m.text} —
                    </div>
                  );
                }
                const isUser = m.from === "You";
                const icon = getAgentIcon(m.from);
                return (
                  <div key={idx} style={{ marginBottom: 20, display: "flex", gap: 12, alignItems: "flex-start", flexDirection: isUser ? "row-reverse" : "row" }}>
                    {!isUser && (
                      <div style={{ width: 32, height: 32, borderRadius: "50%", overflow: "hidden", background: "#333", flexShrink: 0 }}>
                        {icon ? <img src={icon} alt={m.from} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : m.from.charAt(0)}
                      </div>
                    )}
                    <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4, color: isUser ? "#4a9eff" : "#888" }}>{m.from}</div>
                      <div style={{
                        background: isUser ? "#4a9eff" : "rgba(255,255,255,0.05)",
                        padding: "10px 14px",
                        borderRadius: isUser ? "16px 4px 16px 16px" : "4px 16px 16px 16px",
                        fontSize: 15,
                        lineHeight: 1.5,
                        color: isUser ? "white" : "rgba(255,255,255,0.9)",
                        maxWidth: "80%",
                      }}>
                        {m.text}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* DM Input */}
          <div style={{ padding: 24, background: "rgba(0,0,0,0.2)", borderTop: "1px solid rgba(255,255,255,0.1)" }}>
            <div style={{ display: "flex", gap: 12 }}>
              <input
                value={dmInput}
                onChange={(e) => setDmInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendDm()}
                placeholder={`Message ${dmOpen}...`}
                style={{
                  flex: 1,
                  padding: "14px 18px",
                  borderRadius: 14,
                  border: "1px solid rgba(255,255,255,0.1)",
                  background: "rgba(255,255,255,0.05)",
                  color: "white",
                  outline: "none"
                }}
              />
              <button
                onClick={sendDm}
                style={{
                  padding: "0 24px",
                  borderRadius: 14,
                  background: "#4a9eff",
                  color: "white",
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer"
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
