/* global React */
const { useState } = React;

/* --- Icons (inline SVG, copied from codebase) --- */
const IconFork = ({ size = 12 }) => (
  <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
    <path d="M5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM5 12.75a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM4.25 4.5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5a.75.75 0 0 1 .75-.75ZM11 4.5a.75.75 0 0 1 .75.75v1a2.25 2.25 0 0 1-2.25 2.25H6.56l1.22-1.22a.75.75 0 0 0-1.06-1.06l-2.5 2.5a.75.75 0 0 0 0 1.06l2.5 2.5a.75.75 0 1 0 1.06-1.06L6.56 10h2.94A3.75 3.75 0 0 0 13.25 6.25v-1A.75.75 0 0 0 12.5 4.5Z"/>
  </svg>
);

/* --- Button --- */
function Button({ children, variant = "primary", size = "md", disabled, onClick, type = "button", className = "" }) {
  const variants = {
    primary:   "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-300",
    secondary: "bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 disabled:opacity-60",
    ghost:     "bg-transparent text-slate-600 hover:bg-slate-100 disabled:opacity-60",
    danger:    "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  };
  const sizes = { sm: "px-2.5 py-1 text-xs", md: "px-3.5 py-1.5 text-sm" };
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 ${variants[variant]} ${sizes[size]} ${className}`}>
      {children}
    </button>
  );
}

/* --- Badge --- */
function Badge({ children, tone = "neutral", className = "" }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-700 border-slate-200",
    info:    "bg-sky-50 text-sky-700 border-sky-200",
    success: "bg-emerald-50 text-emerald-700 border-emerald-200",
    warning: "bg-amber-50 text-amber-700 border-amber-200",
    danger:  "bg-rose-50 text-rose-700 border-rose-200",
    brand:   "bg-brand-50 text-brand-700 border-brand-200",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}>
      {children}
    </span>
  );
}

/* --- Card --- */
function Card({ children, className = "", onClick }) {
  return (
    <div onClick={onClick}
      className={`rounded-lg border border-slate-200 bg-white shadow-sm transition hover:shadow ${onClick ? "cursor-pointer hover:border-brand-300" : ""} ${className}`}>
      {children}
    </div>
  );
}

/* --- Spinner --- */
function Spinner({ size = 16, className = "" }) {
  return (
    <span role="status" aria-label="Loading"
      className={`inline-block animate-spin rounded-full border-2 border-slate-300 border-t-brand-600 ${className}`}
      style={{ width: size, height: size }} />
  );
}

/* --- Confidence badge --- */
const CONF_TONE  = { sourced: "success", mixed: "info", inferred: "warning", opinion: "neutral" };
const CONF_LABEL = { sourced: "Sourced", mixed: "Mixed",  inferred: "Inferred", opinion: "Opinion" };
function ConfidenceBadge({ level }) {
  return <Badge tone={CONF_TONE[level]}>{CONF_LABEL[level]}</Badge>;
}

/* --- Eyebrow --- */
function Eyebrow({ children, className = "" }) {
  return <span className={`text-xs font-medium uppercase tracking-wide text-slate-400 ${className}`}>{children}</span>;
}

/* Export globally */
Object.assign(window, { Button, Badge, Card, Spinner, ConfidenceBadge, Eyebrow, IconFork });
