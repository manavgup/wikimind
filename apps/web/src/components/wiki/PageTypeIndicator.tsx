import type { PageType } from "../../types/api";
import { Badge, type BadgeTone } from "../shared/Badge";

const PAGE_TYPE_CONFIG: Record<
  PageType,
  { label: string; tone: BadgeTone }
> = {
  source: { label: "Source", tone: "info" },
  concept: { label: "Concept", tone: "brand" },
  answer: { label: "Answer", tone: "success" },
  index: { label: "Index", tone: "neutral" },
  meta: { label: "Meta", tone: "neutral" },
};

interface PageTypeIndicatorProps {
  pageType: PageType;
  className?: string;
}

export function PageTypeIndicator({ pageType, className }: PageTypeIndicatorProps) {
  const config = PAGE_TYPE_CONFIG[pageType];
  if (!config) return null;

  return (
    <Badge tone={config.tone} className={className}>
      {config.label}
    </Badge>
  );
}
