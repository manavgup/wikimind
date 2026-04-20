import { Navigate, Route, Routes } from "react-router-dom";
import AuthCallback from "./components/auth/AuthCallback";
import AuthProvider from "./components/auth/AuthProvider";
import ProtectedRoute from "./components/auth/ProtectedRoute";
import { LandingPage } from "./components/landing/LandingPage";
import { Layout } from "./components/shared/Layout";
import { InboxView } from "./components/inbox/InboxView";
import { WikiExplorerView } from "./components/wiki/WikiExplorerView";
import { AskView } from "./components/ask/AskView";
import { GraphView } from "./components/graph/GraphView";
import { HealthView } from "./components/health/HealthView";
import { SettingsView } from "./components/settings/SettingsView";
import { useWebSocket } from "./hooks/useWebSocket";
import { LandingRoute } from "./components/auth/LandingRoute";

export function App() {
  // Open the gateway WebSocket exactly once for the whole app.
  useWebSocket();

  return (
    <AuthProvider>
      <Routes>
        <Route
          path="/"
          element={
            <LandingRoute>
              <LandingPage />
            </LandingRoute>
          }
        />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/callback" element={<AuthCallback />} />
        <Route
          path="*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/inbox" element={<InboxView />} />
                  <Route path="/ask" element={<AskView />} />
                  <Route path="/ask/:conversationId" element={<AskView />} />
                  <Route path="/wiki" element={<WikiExplorerView />} />
                  <Route path="/wiki/:slug" element={<WikiExplorerView />} />
                  <Route path="/graph" element={<GraphView />} />
                  <Route path="/health" element={<HealthView />} />
                  <Route path="/settings" element={<SettingsView />} />
                  <Route path="*" element={<Navigate to="/inbox" replace />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
