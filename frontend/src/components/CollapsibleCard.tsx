import type { ReactNode } from "react";
import Icon from "./Icon";

interface CollapsibleCardProps {
  id: string;
  collapsed: boolean;
  onToggle: (id: string) => void;
  /** Full header content. When empty, renders chevron inside content area. */
  title?: ReactNode;
  /** Right-side elements in header (before chevron). */
  headerRight?: ReactNode;
  cardClassName?: string;
  headerClassName?: string;
  /** Collapsible body. When empty, chevron hidden, collapse disabled. */
  children?: ReactNode;
}

export default function CollapsibleCard({
  id,
  collapsed,
  onToggle,
  title,
  headerRight,
  cardClassName = "",
  headerClassName = "",
  children,
}: CollapsibleCardProps) {
  const hasContent = Boolean(children);
  const hasHeader = Boolean(title);

  return (
    <div className={`tool-card${cardClassName ? ` ${cardClassName}` : ""}`}>
      {hasHeader && (
        <div
          className={`tool-card-header${headerClassName ? ` ${headerClassName}` : ""}`}
          onClick={() => hasContent && onToggle(id)}
        >
          {title}
          <span className="shell-call-right">
            {headerRight}
            {hasContent && (
              <Icon
                name={collapsed ? "chevron-down" : "chevron-up"}
                size={14}
                className="card-chevron"
                onClick={() => onToggle(id)}
              />
            )}
          </span>
        </div>
      )}

      {hasContent && !collapsed && (
        <div className="tool-card-body card-body--relative">
          {!hasHeader && (
            <Icon
              name={collapsed ? "chevron-down" : "chevron-up"}
              size={14}
              className="card-chevron card-chevron--overlay"
              onClick={() => onToggle(id)}
            />
          )}
          {children}
        </div>
      )}
    </div>
  );
}
