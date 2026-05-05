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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings().then(({ gatewayUrl, authToken }) => {
      setUrl(gatewayUrl);
      setToken(authToken);
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
    setTimeout(() => setSaved(false), 2000);
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
          setUrl((e.target as HTMLInputElement).value);
          setSaved(false);
          setError(null);
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
          setToken((e.target as HTMLInputElement).value);
          setSaved(false);
          setError(null);
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
        placeholder="Paste your API token"
      />
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          chrome.tabs.create({ url: `${url.replace(/\/$/, "")}/auth/tokens` });
        }}
        style={{
          display: "block",
          fontSize: "11px",
          color: "#6366f1",
          margin: "4px 0 0",
          textDecoration: "none",
        }}
      >
        Generate a token on your server &rarr;
      </a>

      {error && (
        <p style={{ fontSize: "11px", color: "#ef4444", margin: "4px 0 0" }}>
          {error}
        </p>
      )}

      <button
        onClick={handleSave}
        style={{
          marginTop: "12px",
          width: "100%",
          padding: "8px",
          borderRadius: "6px",
          border: "none",
          cursor: "pointer",
          fontWeight: 600,
          fontSize: "13px",
          backgroundColor: saved ? "#22c55e" : "#6366f1",
          color: "white",
          transition: "background-color 0.15s",
        }}
      >
        {saved ? "Saved!" : "Save"}
      </button>
    </div>
  );
}
