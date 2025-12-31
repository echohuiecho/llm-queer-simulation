"use client";

import { useEffect, useState } from "react";

interface PlotNode {
  id: number;
  beat: string;
  goal: string;
  stakes: string;
  completed: boolean;
  current: boolean;
  upcoming: boolean;
}

interface PlotState {
  node_idx: number;
  node_turns: number;
  total_turns: number;
  current_beat: string | null;
  current_goal: string | null;
  current_stakes: string | null;
  exit_conditions: string[];
  total_nodes: number;
  overall_progress: number;
  node_progress: number;
  node_budget: {
    min: number;
    target: number;
    hard_cap: number;
  };
  all_nodes: PlotNode[];
  director_controls: {
    pace?: string;
    spice?: number;
    angst?: number;
    comedy?: number;
  };
  director_goal?: string;
  quality_flags?: Record<string, number>;
}

interface RoleArenaStatus {
  enabled: boolean;
  mode: string;
  plot_state?: PlotState;
}

export default function PlotProgression() {
  const [status, setStatus] = useState<RoleArenaStatus | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const response = await fetch("http://localhost:8000/api/rolearena/status");
        const data = await response.json();
        setStatus(data);
      } catch (error) {
        console.error("Failed to fetch RoleArena status:", error);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 2000); // Poll every 2 seconds

    return () => clearInterval(interval);
  }, []);

  if (!status || !status.enabled || !status.plot_state) {
    return null; // Don't show if RoleArena is not enabled
  }

  const plot = status.plot_state;
  const currentNode = plot.all_nodes.find((n) => n.current) || plot.all_nodes[plot.node_idx];

  return (
    <div
      style={{
        position: "fixed",
        top: 16,
        right: 16,
        width: isExpanded ? 400 : 280,
        maxHeight: "90vh",
        background: "rgba(0, 0, 0, 0.85)",
        backdropFilter: "blur(10px)",
        border: "1px solid rgba(255, 255, 255, 0.1)",
        borderRadius: 16,
        padding: 16,
        zIndex: 1000,
        boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
        transition: "all 0.3s ease",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 12,
          cursor: "pointer",
        }}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#4a9eff",
              boxShadow: "0 0 8px rgba(74, 158, 255, 0.6)",
            }}
          />
          <h3
            style={{
              margin: 0,
              fontSize: 16,
              fontWeight: 600,
              color: "#fff",
            }}
          >
            Plot Progression
          </h3>
        </div>
        <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 12 }}>
          {isExpanded ? "−" : "+"}
        </div>
      </div>

      {/* Current Node Info */}
      <div
        style={{
          marginBottom: 16,
          padding: 12,
          background: "rgba(74, 158, 255, 0.1)",
          borderRadius: 8,
          border: "1px solid rgba(74, 158, 255, 0.2)",
        }}
      >
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "#4a9eff",
            marginBottom: 4,
          }}
        >
          {plot.current_beat || `Node ${plot.node_idx + 1}`}
        </div>
        {plot.current_goal && (
          <div
            style={{
              fontSize: 12,
              color: "rgba(255,255,255,0.7)",
              marginTop: 4,
              lineHeight: 1.4,
            }}
          >
            {plot.current_goal}
          </div>
        )}
      </div>

      {/* Progress Bars */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              color: "rgba(255,255,255,0.6)",
              marginBottom: 4,
            }}
          >
            <span>Overall Story</span>
            <span>{plot.overall_progress.toFixed(0)}%</span>
          </div>
          <div
            style={{
              width: "100%",
              height: 6,
              background: "rgba(255,255,255,0.1)",
              borderRadius: 3,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${plot.overall_progress}%`,
                height: "100%",
                background: "linear-gradient(90deg, #4a9eff, #6bb6ff)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>

        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontSize: 11,
              color: "rgba(255,255,255,0.6)",
              marginBottom: 4,
            }}
          >
            <span>Current Node</span>
            <span>
              {plot.node_turns}/{plot.node_budget.target} turns
            </span>
          </div>
          <div
            style={{
              width: "100%",
              height: 6,
              background: "rgba(255,255,255,0.1)",
              borderRadius: 3,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${plot.node_progress}%`,
                height: "100%",
                background: "linear-gradient(90deg, #8b5cf6, #a78bfa)",
                transition: "width 0.3s ease",
              }}
            />
          </div>
        </div>
      </div>

      {/* Expanded View: All Nodes */}
      {isExpanded && (
        <div
          style={{
            flex: 1,
            overflowY: "auto",
            marginTop: 8,
            paddingRight: 4,
          }}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "rgba(255,255,255,0.8)",
              marginBottom: 8,
            }}
          >
            Story Arc ({plot.node_idx + 1}/{plot.total_nodes})
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {plot.all_nodes.map((node, idx) => (
              <div
                key={node.id}
                style={{
                  padding: 10,
                  borderRadius: 8,
                  background: node.current
                    ? "rgba(74, 158, 255, 0.15)"
                    : node.completed
                    ? "rgba(34, 197, 94, 0.1)"
                    : "rgba(255,255,255,0.05)",
                  border: node.current
                    ? "1px solid rgba(74, 158, 255, 0.4)"
                    : node.completed
                    ? "1px solid rgba(34, 197, 94, 0.3)"
                    : "1px solid rgba(255,255,255,0.1)",
                  opacity: node.upcoming ? 0.5 : 1,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 4,
                  }}
                >
                  <div
                    style={{
                      width: 20,
                      height: 20,
                      borderRadius: "50%",
                      background: node.current
                        ? "#4a9eff"
                        : node.completed
                        ? "#22c55e"
                        : "rgba(255,255,255,0.2)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 10,
                      fontWeight: 600,
                      color: node.current || node.completed ? "#fff" : "rgba(255,255,255,0.5)",
                    }}
                  >
                    {node.completed ? "✓" : idx + 1}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: node.current ? 600 : 500,
                      color: node.current
                        ? "#4a9eff"
                        : node.completed
                        ? "#22c55e"
                        : "rgba(255,255,255,0.7)",
                    }}
                  >
                    {node.beat}
                  </div>
                </div>
                {node.current && node.goal && (
                  <div
                    style={{
                      fontSize: 11,
                      color: "rgba(255,255,255,0.6)",
                      marginTop: 4,
                      lineHeight: 1.4,
                    }}
                  >
                    {node.goal}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Director Goal (if available) */}
      {isExpanded && plot.director_goal && (
        <div
          style={{
            marginTop: 12,
            padding: 10,
            background: "rgba(255, 193, 7, 0.1)",
            borderRadius: 8,
            border: "1px solid rgba(255, 193, 7, 0.2)",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: "#ffc107",
              marginBottom: 4,
            }}
          >
            Director's Vision
          </div>
          <div
            style={{
              fontSize: 11,
              color: "rgba(255,255,255,0.7)",
              lineHeight: 1.4,
            }}
          >
            {plot.director_goal}
          </div>
        </div>
      )}

      {/* Controls (if available) */}
      {isExpanded && plot.director_controls && (
        <div
          style={{
            marginTop: 12,
            padding: 10,
            background: "rgba(255,255,255,0.05)",
            borderRadius: 8,
            fontSize: 11,
            color: "rgba(255,255,255,0.6)",
          }}
        >
          <div style={{ marginBottom: 4, fontWeight: 600, color: "rgba(255,255,255,0.8)" }}>
            Controls
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {plot.director_controls.pace && (
              <span>Pace: {plot.director_controls.pace}</span>
            )}
            {plot.director_controls.spice !== undefined && (
              <span>Spice: {plot.director_controls.spice}/3</span>
            )}
            {plot.director_controls.angst !== undefined && (
              <span>Angst: {plot.director_controls.angst}/3</span>
            )}
            {plot.director_controls.comedy !== undefined && (
              <span>Comedy: {plot.director_controls.comedy}/2</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

