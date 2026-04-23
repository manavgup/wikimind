import { useState } from "preact/hooks";
import { ClipTab } from "./ClipTab";
import { AskTab } from "./AskTab";
import { Settings } from "./Settings";

export type Tab = "clip" | "ask";
type View = "main" | "settings";

const TAB_STYLE = {
  flex: 1,
  padding: "8px",
  border: "none",
  cursor: "pointer",
  fontSize: "13px",
  fontWeight: 600,
  transition: "color 0.15s, border-color 0.15s",
  background: "none",
  borderBottom: "2px solid transparent",
} as const;

function activeTabStyle(active: boolean) {
  return {
    ...TAB_STYLE,
    color: active ? "#4673ad" : "#94a3b8",
    borderBottomColor: active ? "#4673ad" : "transparent",
  };
}

export function App() {
  const [view, setView] = useState<View>("main");
  const [tab, setTab] = useState<Tab>("clip");

  if (view === "settings") {
    return <Settings onBack={() => setView("main")} />;
  }

  return (
    <div style={{ padding: "16px" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "12px",
        }}
      >
        <h1 style={{ fontSize: "16px", fontWeight: 700, margin: 0 }}>
          WikiMind
        </h1>
        <button
          onClick={() => setView("settings")}
          aria-label="Settings"
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "18px",
            padding: "4px",
            color: "#64748b",
          }}
        >
          &#9881;
        </button>
      </header>

      <nav
        style={{
          display: "flex",
          borderBottom: "1px solid #e2e8f0",
          marginBottom: "12px",
        }}
      >
        <button style={activeTabStyle(tab === "clip")} onClick={() => setTab("clip")}>
          Clip
        </button>
        <button style={activeTabStyle(tab === "ask")} onClick={() => setTab("ask")}>
          Ask
        </button>
      </nav>

      {tab === "clip" ? <ClipTab /> : <AskTab />}
    </div>
  );
}
