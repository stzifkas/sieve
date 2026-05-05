import { useState } from "react";

const COLORS = {
  bg: "transparent",
  card: "#0a0a0f",
  cardBorder: "#1a1a2e",
  cardHover: "#12121f",
  accent: "#22d3ee",
  accentDim: "#0e7490",
  warn: "#f59e0b",
  success: "#10b981",
  error: "#ef4444",
  text: "#e2e8f0",
  textDim: "#64748b",
  textMuted: "#475569",
  flow: "#334155",
  highlight: "rgba(34, 211, 238, 0.08)",
};

const components = [
  {
    id: "agent",
    label: "LLM Coding Agent",
    sub: "Claude Code · OpenHands · Aider · SWE-agent",
    x: 50, y: 0, w: 500, h: 70,
    color: COLORS.textDim,
    type: "external"
  },
  {
    id: "executor",
    label: "Executor",
    sub: "Runs command verbatim, captures stdout/stderr/exit code",
    x: 50, y: 110, w: 155, h: 90,
    color: COLORS.accent,
    type: "core"
  },
  {
    id: "router",
    label: "Parser Router",
    sub: "Command pattern → Output signature → Fallback",
    x: 222, y: 110, w: 155, h: 90,
    color: COLORS.accent,
    type: "core"
  },
  {
    id: "session",
    label: "Session State",
    sub: "Previous outputs · Seen errors · Read files · Test states",
    x: 395, y: 110, w: 155, h: 90,
    color: COLORS.warn,
    type: "state"
  },
  {
    id: "parsers",
    label: "Domain Parsers",
    sub: null,
    x: 50, y: 240, w: 500, h: 160,
    color: COLORS.accent,
    type: "parsers"
  },
  {
    id: "delta",
    label: "Delta Engine",
    sub: "Diffs current output against session history",
    x: 50, y: 440, w: 240, h: 80,
    color: COLORS.success,
    type: "core"
  },
  {
    id: "formatter",
    label: "Formatter",
    sub: "plain · structured · xml · minimal",
    x: 310, y: 440, w: 240, h: 80,
    color: COLORS.success,
    type: "core"
  },
  {
    id: "output",
    label: "Compressed Output → Agent",
    sub: "60-80% fewer tokens",
    x: 50, y: 560, w: 500, h: 70,
    color: COLORS.success,
    type: "result"
  }
];

const parsers = [
  { label: "Compiler", items: ["gcc/clang", "rustc", "tsc", "javac", "mypy", "eslint"], color: COLORS.error, prio: "P0-P2" },
  { label: "Test", items: ["pytest", "jest", "go test", "unittest", "mocha", "rspec"], color: COLORS.warn, prio: "P0-P1" },
  { label: "Build", items: ["pip", "npm", "cargo", "make", "gradle", "docker"], color: COLORS.accentDim, prio: "P1-P3" },
  { label: "Runtime", items: ["Python TB", "Node err", "segfault", "OOM"], color: "#a855f7", prio: "P0-P2" },
  { label: "File I/O", items: ["find/ls", "grep/rg", "cat", "tree"], color: "#6366f1", prio: "P2" },
  { label: "Fallback", items: ["line dedup", "truncation", "head+tail"], color: COLORS.textDim, prio: "P0" },
];

const flows = [
  { from: "agent", to: "executor", label: "tool_call(cmd)" },
  { from: "executor", to: "router", label: "raw output" },
  { from: "router", to: "parsers", label: "route" },
  { from: "session", to: "delta", label: "history", style: "dashed" },
  { from: "parsers", to: "delta", label: "structured" },
  { from: "delta", to: "formatter", label: "compressed" },
  { from: "formatter", to: "output", label: "" },
];

const stats = [
  { label: "Raw pytest output", tokens: 847, compressed: 127, ratio: "85%" },
  { label: "GCC error cascade", tokens: 312, compressed: 58, ratio: "81%" },
  { label: "pip install (success)", tokens: 2400, compressed: 12, ratio: "99.5%" },
  { label: "Python traceback", tokens: 180, compressed: 52, ratio: "71%" },
  { label: "Test re-run (delta)", tokens: 847, compressed: 34, ratio: "96%" },
];

function Card({ comp, isHovered, onHover }) {
  const isParser = comp.type === "parsers";
  return (
    <div
      onMouseEnter={() => onHover(comp.id)}
      onMouseLeave={() => onHover(null)}
      style={{
        position: "absolute",
        left: comp.x,
        top: comp.y,
        width: comp.w,
        height: comp.h,
        background: isHovered ? COLORS.cardHover : COLORS.card,
        border: `1px solid ${isHovered ? comp.color : COLORS.cardBorder}`,
        borderRadius: 8,
        padding: isParser ? "12px 16px" : "12px 16px",
        transition: "all 0.2s ease",
        boxShadow: isHovered ? `0 0 20px ${comp.color}15` : "none",
        overflow: "hidden",
      }}
    >
      {!isParser && (
        <>
          <div style={{
            fontSize: 13,
            fontWeight: 600,
            color: comp.color,
            letterSpacing: "0.02em",
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}>
            {comp.label}
          </div>
          {comp.sub && (
            <div style={{
              fontSize: 10.5,
              color: COLORS.textMuted,
              marginTop: 4,
              lineHeight: 1.4,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
            }}>
              {comp.sub}
            </div>
          )}
        </>
      )}
      {isParser && (
        <>
          <div style={{
            fontSize: 12,
            fontWeight: 600,
            color: COLORS.accent,
            marginBottom: 10,
            fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
          }}>
            Domain Parsers
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
            {parsers.map((p, i) => (
              <div key={i} style={{
                background: `${p.color}10`,
                border: `1px solid ${p.color}30`,
                borderRadius: 5,
                padding: "6px 8px",
              }}>
                <div style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: p.color,
                  marginBottom: 3,
                  fontFamily: "'JetBrains Mono', monospace",
                }}>
                  {p.label}
                  <span style={{ color: COLORS.textMuted, fontWeight: 400, marginLeft: 4, fontSize: 8 }}>
                    {p.prio}
                  </span>
                </div>
                <div style={{
                  fontSize: 8.5,
                  color: COLORS.textMuted,
                  lineHeight: 1.5,
                  fontFamily: "'JetBrains Mono', monospace",
                }}>
                  {p.items.join(" · ")}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function CompressionBar({ stat }) {
  const pct = ((stat.tokens - stat.compressed) / stat.tokens) * 100;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: 10,
        fontFamily: "'JetBrains Mono', monospace",
        color: COLORS.textDim,
        marginBottom: 3,
      }}>
        <span>{stat.label}</span>
        <span>
          <span style={{ color: COLORS.textMuted }}>{stat.tokens}→</span>
          <span style={{ color: COLORS.success, fontWeight: 600 }}>{stat.compressed}</span>
          <span style={{ color: COLORS.textMuted }}> tok</span>
        </span>
      </div>
      <div style={{
        width: "100%",
        height: 6,
        background: COLORS.cardBorder,
        borderRadius: 3,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${pct}%`,
          height: "100%",
          background: `linear-gradient(90deg, ${COLORS.accentDim}, ${COLORS.success})`,
          borderRadius: 3,
          transition: "width 0.6s ease",
        }} />
      </div>
      <div style={{
        fontSize: 8,
        color: COLORS.success,
        textAlign: "right",
        marginTop: 1,
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        {stat.ratio} saved
      </div>
    </div>
  );
}

export default function AgentCompressArch() {
  const [hovered, setHovered] = useState(null);
  const [activeTab, setActiveTab] = useState("arch");

  return (
    <div style={{
      width: "100%",
      minHeight: 700,
      color: COLORS.text,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace",
      padding: 24,
    }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{
          fontSize: 20,
          fontWeight: 700,
          color: COLORS.accent,
          margin: 0,
          letterSpacing: "-0.02em",
        }}>
          agent-compress
        </h1>
        <p style={{
          fontSize: 11,
          color: COLORS.textDim,
          margin: "4px 0 0 0",
        }}>
          Transparent feedback compression middleware for LLM coding agents
        </p>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {["arch", "compression", "pipeline"].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "6px 14px",
              fontSize: 10,
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: activeTab === tab ? 600 : 400,
              background: activeTab === tab ? `${COLORS.accent}15` : "transparent",
              color: activeTab === tab ? COLORS.accent : COLORS.textMuted,
              border: `1px solid ${activeTab === tab ? COLORS.accentDim : COLORS.cardBorder}`,
              borderRadius: 5,
              cursor: "pointer",
              transition: "all 0.15s ease",
              textTransform: "capitalize",
            }}
          >
            {tab === "arch" ? "Architecture" : tab === "compression" ? "Compression Ratios" : "Data Pipeline"}
          </button>
        ))}
      </div>

      {activeTab === "arch" && (
        <div style={{ position: "relative", height: 650, width: 600 }}>
          {components.map(c => (
            <Card
              key={c.id}
              comp={c}
              isHovered={hovered === c.id}
              onHover={setHovered}
            />
          ))}
          {/* Flow arrows as simple SVG */}
          <svg
            style={{ position: "absolute", top: 0, left: 0, width: 600, height: 650, pointerEvents: "none" }}
          >
            <defs>
              <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                <polygon points="0 0, 8 3, 0 6" fill={COLORS.textMuted} />
              </marker>
            </defs>
            {/* agent → executor */}
            <line x1="130" y1="70" x2="130" y2="110" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
            {/* executor → router */}
            <line x1="205" y1="155" x2="222" y2="155" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
            {/* router → parsers */}
            <line x1="300" y1="200" x2="300" y2="240" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
            {/* parsers → delta */}
            <line x1="200" y1="400" x2="200" y2="440" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
            {/* session → delta */}
            <line x1="472" y1="200" x2="472" y2="420" stroke={COLORS.flow} strokeWidth="1" strokeDasharray="4,4" opacity="0.4" />
            <line x1="472" y1="420" x2="290" y2="460" stroke={COLORS.flow} strokeWidth="1" strokeDasharray="4,4" opacity="0.4" markerEnd="url(#arrowhead)" />
            {/* delta → formatter */}
            <line x1="290" y1="480" x2="310" y2="480" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
            {/* formatter → output */}
            <line x1="430" y1="520" x2="430" y2="560" stroke={COLORS.flow} strokeWidth="1" markerEnd="url(#arrowhead)" />
          </svg>

          {/* Labels on flows */}
          <div style={{ position: "absolute", left: 135, top: 82, fontSize: 8, color: COLORS.textMuted }}>
            tool_call(cmd)
          </div>
          <div style={{ position: "absolute", left: 305, top: 215, fontSize: 8, color: COLORS.textMuted }}>
            route to parser
          </div>
          <div style={{ position: "absolute", left: 205, top: 415, fontSize: 8, color: COLORS.textMuted }}>
            structured output
          </div>
          <div style={{ position: "absolute", left: 478, top: 300, fontSize: 8, color: COLORS.warn, opacity: 0.6 }}>
            history
          </div>
        </div>
      )}

      {activeTab === "compression" && (
        <div style={{
          background: COLORS.card,
          border: `1px solid ${COLORS.cardBorder}`,
          borderRadius: 8,
          padding: 20,
          maxWidth: 500,
        }}>
          <div style={{
            fontSize: 12,
            fontWeight: 600,
            color: COLORS.accent,
            marginBottom: 16,
          }}>
            Compression ratios by output type
          </div>
          {stats.map((s, i) => (
            <CompressionBar key={i} stat={s} />
          ))}
          <div style={{
            marginTop: 16,
            padding: "10px 12px",
            background: `${COLORS.success}08`,
            border: `1px solid ${COLORS.success}20`,
            borderRadius: 6,
            fontSize: 10,
            color: COLORS.success,
            lineHeight: 1.6,
          }}>
            <strong>Compound effect:</strong> In a 20-turn debug session with 5 test reruns,
            delta compression reduces total observation tokens from ~17K to ~2.8K — an 83% reduction
            on the fastest-growing cost center.
          </div>
        </div>
      )}

      {activeTab === "pipeline" && (
        <div style={{ maxWidth: 560 }}>
          {[
            {
              step: "1",
              title: "Intercept",
              desc: "Agent calls tool → agent-compress captures raw stdout/stderr/exit_code",
              tokens: "0 overhead",
              color: COLORS.textDim,
            },
            {
              step: "2",
              title: "Classify",
              desc: "Parser Router matches command pattern (pytest?) then output signature (FAILURES header?)",
              tokens: "<1ms",
              color: COLORS.accent,
            },
            {
              step: "3",
              title: "Parse",
              desc: "Domain parser extracts structured fields: test ID, file, line, assertion, actual vs expected",
              tokens: "847 → 142 tokens",
              color: COLORS.warn,
            },
            {
              step: "4",
              title: "Delta",
              desc: "Compare against session state. If test_user_update passed before and now fails, emit only the change",
              tokens: "142 → 34 tokens (re-run)",
              color: COLORS.success,
            },
            {
              step: "5",
              title: "Dedup",
              desc: "If this exact error was seen in turn 3, emit '[same as turn 3]' instead of full error",
              tokens: "Eliminates repeats",
              color: "#a855f7",
            },
            {
              step: "6",
              title: "Format & Return",
              desc: "Compressed output returned to agent as if it were the raw tool result. Agent sees clean, actionable signal",
              tokens: "~85% smaller",
              color: COLORS.accent,
            },
          ].map((s, i) => (
            <div key={i} style={{
              display: "flex",
              gap: 14,
              marginBottom: 2,
              position: "relative",
            }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: `${s.color}18`,
                border: `1.5px solid ${s.color}50`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 700,
                color: s.color,
                flexShrink: 0,
                marginTop: 2,
              }}>
                {s.step}
              </div>
              {i < 5 && (
                <div style={{
                  position: "absolute",
                  left: 13,
                  top: 32,
                  width: 1,
                  height: 44,
                  background: COLORS.cardBorder,
                }} />
              )}
              <div style={{
                background: COLORS.card,
                border: `1px solid ${COLORS.cardBorder}`,
                borderRadius: 6,
                padding: "10px 14px",
                flex: 1,
                marginBottom: 12,
              }}>
                <div style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 4,
                }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: s.color }}>
                    {s.title}
                  </span>
                  <span style={{
                    fontSize: 9,
                    color: COLORS.success,
                    background: `${COLORS.success}10`,
                    padding: "2px 6px",
                    borderRadius: 3,
                  }}>
                    {s.tokens}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: COLORS.textMuted, lineHeight: 1.5 }}>
                  {s.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
