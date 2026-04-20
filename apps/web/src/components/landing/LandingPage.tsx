import { useState, useCallback } from "react";
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

  const openLogin = useCallback(() => {
    setShowLogin(true);
    document.body.style.overflow = "hidden";
  }, []);

  const closeLogin = useCallback(() => {
    setShowLogin(false);
    document.body.style.overflow = "";
  }, []);

  return (
    <div className="bg-white" style={{ fontSize: "16px", lineHeight: "1.55", color: "#334155" }}>
      {/* Top nav */}
      <nav
        className="sticky top-0 z-40 border-b border-slate-200"
        style={{ background: "rgba(255, 255, 255, 0.9)", backdropFilter: "blur(8px)", WebkitBackdropFilter: "blur(8px)" }}
      >
        <div className="mx-auto flex h-[60px] max-w-[1120px] items-center justify-between px-8">
          <a
            href="#top"
            className="flex items-center gap-2 text-[15px] font-semibold text-slate-900"
            style={{ letterSpacing: "-0.01em" }}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById("top")?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            <span className="text-lg">&#x1f9e0;</span>
            <span>WikiMind</span>
          </a>
          <div className="flex items-center gap-6">
            <a
              href="#how"
              className="hidden text-[13px] font-medium text-slate-500 transition-colors duration-100 hover:text-slate-900 sm:inline"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("how")?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              How it works
            </a>
            <a
              href="#architecture"
              className="hidden text-[13px] font-medium text-slate-500 transition-colors duration-100 hover:text-slate-900 sm:inline"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("architecture")?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              Architecture
            </a>
            <a
              href="#cases"
              className="hidden text-[13px] font-medium text-slate-500 transition-colors duration-100 hover:text-slate-900 sm:inline"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("cases")?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              Use cases
            </a>
            <a
              href="#faq"
              className="hidden text-[13px] font-medium text-slate-500 transition-colors duration-100 hover:text-slate-900 sm:inline"
              onClick={(e) => {
                e.preventDefault();
                document.getElementById("faq")?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              FAQ
            </a>
            <button
              type="button"
              onClick={openLogin}
              className="rounded-md bg-brand-700 px-3.5 py-1.5 text-[13px] font-medium text-white transition-colors duration-100 hover:bg-brand-800"
            >
              Sign in
            </button>
          </div>
        </div>
      </nav>

      <HeroSection onSignIn={openLogin} />
      <ProblemSolutionSection />
      <OperationsSection />
      <PullQuoteSection />
      <ArchitectureSection />
      <UseCasesSection />
      <MemexSection />
      <FaqSection />
      <CtaBandSection onSignIn={openLogin} />
      <FooterSection onSignIn={openLogin} />
      {showLogin && <LoginOverlay onClose={closeLogin} />}
    </div>
  );
}
