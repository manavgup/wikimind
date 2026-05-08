import { Link } from "react-router-dom";

interface BreadcrumbsProps {
  concept: string | null;
  articleTitle: string;
}

export function Breadcrumbs({ concept, articleTitle }: BreadcrumbsProps) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4 text-sm text-slate-500">
      <ol className="flex items-center gap-1.5">
        <li>
          <Link to="/wiki" className="hover:text-brand-700">
            Wiki
          </Link>
        </li>
        {concept ? (
          <>
            <li aria-hidden="true">
              <ChevronIcon />
            </li>
            <li>
              <Link
                to={`/wiki?concept=${encodeURIComponent(concept)}`}
                className="hover:text-brand-700"
              >
                {concept}
              </Link>
            </li>
          </>
        ) : null}
        <li aria-hidden="true">
          <ChevronIcon />
        </li>
        <li className="truncate font-medium text-slate-900">{articleTitle}</li>
      </ol>
    </nav>
  );
}

function ChevronIcon() {
  return (
    <svg
      className="h-3.5 w-3.5 text-slate-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  );
}
