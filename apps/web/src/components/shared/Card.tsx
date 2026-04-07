import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
}

export function Card({ children, className = "", onClick }: CardProps) {
  const base =
    "rounded-lg border border-slate-200 bg-white shadow-sm transition hover:shadow";
  const interactive = onClick ? "cursor-pointer hover:border-brand-300" : "";
  return (
    <div className={`${base} ${interactive} ${className}`} onClick={onClick}>
      {children}
    </div>
  );
}
