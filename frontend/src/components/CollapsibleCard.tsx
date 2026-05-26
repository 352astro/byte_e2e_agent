import type { ReactNode } from "react";
import Icon from "./Icon";
import { useFocusedId } from "../hooks/FocusContext";

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
  /** If false, header is not clickable (default true). */
  headerClickable?: boolean;
  /** If true, hide the default chevron (use headerRight for custom chevron). */
  hideChevron?: boolean;
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
  headerClickable = true,
  hideChevron = false,
}: CollapsibleCardProps) {
  const focusedId = useFocusedId();
  const isFocused = dataFid && focusedId === dataFid;
  const hasContent = Boolean(children);
  const hasHeader = Boolean(title);
  const showChevron = !hideChevron && hasContent && (hasHeader || standalone);

  return (
    <div
      className={`tool-card${cardClassName ? ` ${cardClassName}` : ""}${isFocused ? " card-latest" : ""}`}
      data-fid={dataFid}
    >
      {hasHeader && (
        <div
          className={`tool-card-header${headerClassName ? ` ${headerClassName}` : ""}`}
          onClick={() => hasContent && headerClickable && onToggle(id)}
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

      {hasContent && (
        <div
          className={`tool-card-body card-body--relative${collapsed ? " tool-card-body--collapsed" : ""}`}
        >
          {!hasHeader && showChevron && (
            <Icon
              name={collapsed ? "chevron-down" : "chevron-up"}
              size={14}
              className="card-chevron card-chevron--overlay"
              onClick={() => onToggle(id)}
            />
          )}
          <div className="tool-card-body-inner">{children}</div>
        </div>
      )}
    </div>
  );
}
