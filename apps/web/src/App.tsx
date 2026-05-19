import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AuthCallback from "./components/auth/AuthCallback";
import AuthProvider from "./components/auth/AuthProvider";
import ProtectedRoute from "./components/auth/ProtectedRoute";
import { Layout } from "./components/shared/Layout";
import { Spinner } from "./components/shared/Spinner";
import { useWebSocket } from "./hooks/useWebSocket";
import { LandingRoute } from "./components/auth/LandingRoute";
import { getOnboardingStatus } from "./api/settings";

// Lazy-loaded route-level views for code splitting
const LandingPage = lazy(() =>
  import("./components/landing/LandingPage").then((m) => ({ default: m.LandingPage }))
);
const InboxView = lazy(() =>
  import("./components/inbox/InboxView").then((m) => ({ default: m.InboxView }))
);
const FacetedSearchView = lazy(() =>
  import("./components/wiki/FacetedSearchView").then((m) => ({ default: m.FacetedSearchView }))
);
const WikiExplorerView = lazy(() =>
  import("./components/wiki/WikiExplorerView").then((m) => ({ default: m.WikiExplorerView }))
);
const AskView = lazy(() =>
  import("./components/ask/AskView").then((m) => ({ default: m.AskView }))
);
const GraphView = lazy(() =>
  import("./components/graph/GraphView").then((m) => ({ default: m.GraphView }))
);
const HealthView = lazy(() =>
  import("./components/health/HealthView").then((m) => ({ default: m.HealthView }))
);
const SettingsView = lazy(() =>
  import("./components/settings/SettingsView").then((m) => ({ default: m.SettingsView }))
);
const ShareManagementView = lazy(() =>
  import("./components/settings/ShareManagementView").then((m) => ({
    default: m.ShareManagementView,
  }))
);
const BillingPage = lazy(() =>
  import("./components/settings/BillingPage").then((m) => ({
    default: m.BillingPage,
  }))
);
const SynthesisView = lazy(() =>
  import("./components/synthesis/SynthesisView").then((m) => ({ default: m.SynthesisView }))
);
const AdminDashboard = lazy(() =>
  import("./components/admin/AdminDashboard").then((m) => ({ default: m.AdminDashboard }))
);
const OnboardingWizard = lazy(() =>
  import("./components/onboarding/OnboardingWizard").then((m) => ({ default: m.OnboardingWizard }))
);
const SourceDetailView = lazy(() =>
  import("./components/inbox/SourceDetailView").then((m) => ({ default: m.SourceDetailView }))
);

function AuthenticatedApp() {
  const navigate = useNavigate();
  const { data: onboarding, isLoading: onboardingLoading } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: getOnboardingStatus,
  });

  const showWizard = !onboardingLoading && onboarding && !onboarding.completed;

  return (
    <Layout>
      <Suspense fallback={<Spinner size={24} className="mx-auto mt-12" />}>
        {showWizard ? (
          <OnboardingWizard
            onComplete={() => navigate("/wiki")}
          />
        ) : (
          <Routes>
            <Route path="/inbox" element={<InboxView />} />
            <Route path="/sources/:id" element={<SourceDetailView />} />
            <Route path="/ask" element={<AskView />} />
            <Route path="/ask/:conversationId" element={<AskView />} />
            <Route path="/wiki" element={<WikiExplorerView />} />
            <Route path="/wiki/search" element={<FacetedSearchView />} />
            <Route path="/wiki/:slug" element={<WikiExplorerView />} />
            <Route path="/synthesis" element={<SynthesisView />} />
            <Route path="/graph" element={<GraphView />} />
            <Route path="/health" element={<HealthView />} />
            <Route path="/settings" element={<SettingsView />} />
            <Route path="/settings/billing" element={<BillingPage />} />
            <Route path="/settings/shares" element={<ShareManagementView />} />
            <Route path="/admin" element={<AdminDashboard />} />
            <Route path="*" element={<Navigate to="/inbox" replace />} />
          </Routes>
        )}
      </Suspense>
    </Layout>
  );
}

export function App() {
  // Open the gateway WebSocket exactly once for the whole app.
  useWebSocket();

  return (
    <AuthProvider>
      <Suspense fallback={<Spinner size={24} className="mx-auto mt-12" />}>
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
      </Suspense>
    </AuthProvider>
  );
}
