import { useState, useEffect } from "preact/hooks";
import { getSettings, setGatewayUrl, setAuthToken } from "../../lib/storage";

interface Props {
  onBack: () => void;
}

function isValidUrl(str: string): boolean {
  try {
    const url = new URL(str);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function Settings({ onBack }: Props) {
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings().then(({ gatewayUrl, authToken }) => {
      setUrl(gatewayUrl);
      setToken(authToken);
      // Mark as not dirty if both are already configured
      setDirty(!gatewayUrl || !authToken);
    });
  }, []);

  async function handleSave() {
    if (!isValidUrl(url)) {
      setError("Enter a valid HTTP(S) URL");
      return;
    }
    setError(null);

    const cleanUrl = url.replace(/\/$/, "");
    const origin = new URL(cleanUrl).origin + "/*";

    // Request host permission for non-localhost gateways
    const hasPermission = await chrome.permissions.contains({
      origins: [origin],
    });
    if (!hasPermission) {
      const granted = await chrome.permissions.request({
        origins: [origin],
      });
      if (!granted) {
        setError("Permission denied — extension cannot reach this URL");
        return;
      }
    }

    await setGatewayUrl(cleanUrl);
    await setAuthToken(token.trim());
    setSaved(true);
    setDirty(false);

    // If both URL and token are set, go back to Clip tab after a brief flash
    if (cleanUrl && token.trim()) {
      setTimeout(() => onBack(), 800);
    } else {
      setTimeout(() => setSaved(false), 2000);
    }
  }

  return (
    <div style={{ padding: "16px" }}>
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginBottom: "16px",
        }}
      >
        <button
          onClick={onBack}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: "16px",
            padding: "4px",
            color: "#64748b",
          }}
        >
          &larr;
        </button>
        <h1 style={{ fontSize: "16px", fontWeight: 700, margin: 0 }}>
          Settings
        </h1>
      </header>

      <label
        style={{
          display: "block",
          fontSize: "12px",
          fontWeight: 600,
          color: "#64748b",
          marginBottom: "4px",
        }}
      >
        Gateway URL
      </label>
      <input
        type="url"
        value={url}
        onInput={(e) => {
          const val = (e.target as HTMLInputElement).value;
          setUrl(val);
          setSaved(false);
          setDirty(true);
          setError(null);
          // Persist immediately so the value survives popup close
          chrome.storage.local.set({ gatewayUrl: val });
        }}
        style={{
          width: "100%",
          padding: "8px",
          border: error ? "1px solid #ef4444" : "1px solid #cbd5e1",
          borderRadius: "6px",
          fontSize: "13px",
          boxSizing: "border-box",
          outline: "none",
        }}
        placeholder="https://wikimind.fly.dev"
      />

      <label
        style={{
          display: "block",
          fontSize: "12px",
          fontWeight: 600,
          color: "#64748b",
          marginBottom: "4px",
          marginTop: "12px",
        }}
      >
        API Token
      </label>
      <input
        type="password"
        value={token}
        onInput={(e) => {
          const val = (e.target as HTMLInputElement).value;
          setToken(val);
          setSaved(false);
          setDirty(true);
          setError(null);
          chrome.storage.local.set({ authToken: val });
        }}
        style={{
          width: "100%",
          padding: "8px",
          border: "1px solid #cbd5e1",
          borderRadius: "6px",
          fontSize: "13px",
          boxSizing: "border-box",
          outline: "none",
        }}
        placeholder="Paste your wmk_ API token"
      />
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          const cleanUrl = url.replace(/\/$/, "");
          chrome.tabs.create({ url: `${cleanUrl}/settings` });
        }}
        style={{
          display: "block",
          fontSize: "11px",
          color: "#6366f1",
          margin: "4px 0 0",
          textDecoration: "none",
        }}
      >
        Generate a token in Settings &rarr;
      </a>

      {error && (
        <p style={{ fontSize: "11px", color: "#ef4444", margin: "4px 0 0" }}>
          {error}
        </p>
      )}

      <button
        onClick={handleSave}
        disabled={!dirty && !saved}
        style={{
          marginTop: "12px",
          width: "100%",
          padding: "8px",
          borderRadius: "6px",
          border: "none",
          cursor: dirty ? "pointer" : "not-allowed",
          fontWeight: 600,
          fontSize: "13px",
          backgroundColor: saved ? "#22c55e" : dirty ? "#6366f1" : "#cbd5e1",
          color: "white",
          transition: "background-color 0.15s",
        }}
      >
        {saved ? "Saved!" : "Save"}
      </button>
    </div>
  );
}
