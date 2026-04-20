import { useState } from "react";
import { HeroSection } from "./HeroSection";
import { ProblemSolutionSection } from "./ProblemSolutionSection";
import { OperationsSection } from "./OperationsSection";
import { PullQuoteSection } from "./PullQuoteSection";
import { ArchitectureSection } from "./ArchitectureSection";
import { UseCasesSection } from "./UseCasesSection";
import { MemexSection } from "./MemexSection";
import { FaqSection } from "./FaqSection";
import { CtaBandSection } from "./CtaBandSection";
import { FooterSection } from "./FooterSection";
import { LoginOverlay } from "./LoginOverlay";

export function LandingPage() {
  const [showLogin, setShowLogin] = useState(false);

  const openLogin = () => setShowLogin(true);
  const closeLogin = () => setShowLogin(false);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <HeroSection onSignIn={openLogin} />
      <ProblemSolutionSection />
      <OperationsSection />
      <PullQuoteSection />
      <ArchitectureSection />
      <UseCasesSection />
      <MemexSection />
      <FaqSection />
      <CtaBandSection onSignIn={openLogin} />
      <FooterSection />
      {showLogin && <LoginOverlay onClose={closeLogin} />}
    </div>
  );
}
