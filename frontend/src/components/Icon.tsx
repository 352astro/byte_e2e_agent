import type { SVGProps } from "react";

// ── Path data (viewBox 0 0 24 24, stroke 1.5, round) ──

export type IconName =
  | "bulb"
  | "chevron-up"
  | "chevron-down"
  | "dots-vertical"
  | "restore"
  | "tool"
  | "write";

const paths: Record<IconName, SVGProps<SVGPathElement>> = {
  bulb: {
    d: "M12 3a6 6 0 0 0-6 6c0 2.6 1.6 4.8 4 5.7V17a1 1 0 0 0 1 1h2a1 1 0 0 0 1-1v-2.3c2.4-.9 4-3.1 4-5.7a6 6 0 0 0-6-6zM9 21h6M10 18h4",
  },
  "chevron-up": {
    d: "M18 15l-6-6-6 6",
  },
  "chevron-down": {
    d: "M6 9l6 6 6-6",
  },
  "dots-vertical": {
    d: "M12 5v.01M12 12v.01M12 19v.01",
  },
  restore: {
    d: "M3 10h10a5 5 0 0 1 0 10H8M3 10l4-4M3 10l4 4",
  },
  tool: {
    d: "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",
  },
  write: {
    d: "M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z",
  },
};

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
  onClick?: (e: React.MouseEvent) => void;
}

export default function Icon({
  name,
  size = 16,
  className,
  onClick,
}: IconProps) {
  const p = paths[name];
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      onClick={onClick}
    >
      <path d={p.d as string} />
    </svg>
  );
}
