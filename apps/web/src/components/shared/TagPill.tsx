interface TagPillProps {
  name: string;
  color: string;
  onRemove?: () => void;
  onClick?: () => void;
  className?: string;
}

/**
 * Pill-shaped badge for user tags. Renders with the tag's chosen color
 * as a left border accent and a subtle tinted background.
 */
export function TagPill({
  name,
  color,
  onRemove,
  onClick,
  className = "",
}: TagPillProps) {
  const bgColor = `${color}18`; // ~10% opacity hex suffix

  return (
    <span
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") onClick();
            }
          : undefined
      }
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        onClick ? "cursor-pointer hover:opacity-80" : ""
      } ${className}`}
      style={{
        borderColor: color,
        backgroundColor: bgColor,
        color: color,
      }}
    >
      {name}
      {onRemove ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 opacity-60 hover:opacity-100"
          aria-label={`Remove tag ${name}`}
        >
          x
        </button>
      ) : null}
    </span>
  );
}
