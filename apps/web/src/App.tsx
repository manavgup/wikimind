import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AuthCallback from "./components/auth/AuthCallback";
import AuthProvider from "./components/auth/AuthProvider";
import ProtectedRoute from "./components/auth/ProtectedRoute";
import { LandingPage } from "./components/landing/LandingPage";
import { Layout } from "./components/shared/Layout";
import { InboxView } from "./components/inbox/InboxView";
import { FacetedSearchView } from "./components/wiki/FacetedSearchView";
import { WikiExplorerView } from "./components/wiki/WikiExplorerView";
import { AskView } from "./components/ask/AskView";
import { GraphView } from "./components/graph/GraphView";
import { HealthView } from "./components/health/HealthView";
import { SettingsView } from "./components/settings/SettingsView";
import { SynthesisView } from "./components/synthesis/SynthesisView";
import { OnboardingWizard } from "./components/onboarding/OnboardingWizard";
import { useWebSocket } from "./hooks/useWebSocket";
import { LandingRoute } from "./components/auth/LandingRoute";
import { getOnboardingStatus } from "./api/settings";

function AuthenticatedApp() {
  const navigate = useNavigate();
  const { data: onboarding, isLoading: onboardingLoading } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: getOnboardingStatus,
  });

  const showWizard = !onboardingLoading && onboarding && !onboarding.completed;

  return (
    <Layout>
      {showWizard ? (
        <OnboardingWizard
          onComplete={() => navigate("/wiki")}
        />
      ) : (
        <Routes>
          <Route path="/inbox" element={<InboxView />} />
          <Route path="/ask" element={<AskView />} />
          <Route path="/ask/:conversationId" element={<AskView />} />
          <Route path="/wiki" element={<WikiExplorerView />} />
          <Route path="/wiki/search" element={<FacetedSearchView />} />
          <Route path="/wiki/:slug" element={<WikiExplorerView />} />
          <Route path="/synthesis" element={<SynthesisView />} />
          <Route path="/graph" element={<GraphView />} />
          <Route path="/health" element={<HealthView />} />
          <Route path="/settings" element={<SettingsView />} />
          <Route path="*" element={<Navigate to="/inbox" replace />} />
        </Routes>
      )}
    </Layout>
  );
}

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
              <AuthenticatedApp />
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
