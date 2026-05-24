import type { ReactNode } from "react";
import Icon from "./Icon";

interface CollapsibleCardProps {
  id: string;
  collapsed: boolean;
  onToggle: (id: string) => void;
  title?: ReactNode;
  headerRight?: ReactNode;
  cardClassName?: string;
  headerClassName?: string;
  children?: ReactNode;
  /** If true, shows overlay chevron even without a title (for standalone cards). */
  standalone?: boolean;
  /** Optional data-fid for focus targeting. */
  dataFid?: string;
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
  standalone = false,
  dataFid,
}: CollapsibleCardProps) {
  const hasContent = Boolean(children);
  const hasHeader = Boolean(title);
  const showChevron = hasContent && (hasHeader || standalone);

  return (
    <div className={`tool-card${cardClassName ? ` ${cardClassName}` : ""}`} data-fid={dataFid}>
      {hasHeader && (
        <div
          className={`tool-card-header${headerClassName ? ` ${headerClassName}` : ""}`}
          onClick={() => hasContent && onToggle(id)}
        >
          {title}
          <span className="shell-call-right">
            {headerRight}
            {showChevron && (
              <Icon
                name={collapsed ? "chevron-down" : "chevron-up"}
                size={14}
                className="card-chevron"
              />
            )}
          </span>
        </div>
      )}

      {hasContent && !collapsed && (
        <div className="tool-card-body card-body--relative">
          {!hasHeader && showChevron && (
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
