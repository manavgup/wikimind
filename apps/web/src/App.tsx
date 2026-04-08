import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/shared/Layout";
import { InboxView } from "./components/inbox/InboxView";
import { WikiExplorerView } from "./components/wiki/WikiExplorerView";
import { AskView } from "./components/ask/AskView";
import { useWebSocket } from "./hooks/useWebSocket";

export function App() {
  // Open the gateway WebSocket exactly once for the whole app.
  useWebSocket();

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/inbox" replace />} />
        <Route path="/inbox" element={<InboxView />} />
        <Route path="/ask" element={<AskView />} />
        <Route path="/ask/:conversationId" element={<AskView />} />
        <Route path="/wiki" element={<WikiExplorerView />} />
        <Route path="/wiki/:slug" element={<WikiExplorerView />} />
        <Route path="*" element={<Navigate to="/inbox" replace />} />
      </Routes>
    </Layout>
  );
}
