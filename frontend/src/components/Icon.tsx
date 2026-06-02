import type { SVGProps } from "react";

// ── Path data (viewBox 0 0 24 24, stroke 1.5, round) ──

export type IconName =
    | "bulb"
    | "chevron-up"
    | "chevron-down"
    | "dots-vertical"
    | "replay"
    | "git-graph"
    | "undo"
    | "tool"
    | "terminal"
    | "error"
    | "write"
    | "book-open"
    | "check"
    | "flag"
    | "settings"
    | "palette"
    | "robot"
    | "trash";

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
    check: {
        d: "M20 6L9 17l-5-5",
    },
    flag: {
        d: "M5 21V3l10 6-10 6",
    },
    trash: {
        d: "M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15M10 11v6M14 11v6",
    },
    settings: {
        d: "M12 15.5A3.5 3.5 0 1 0 12 8a3.5 3.5 0 0 0 0 7.5zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 8.92 4.6 1.65 1.65 0 0 0 10 3.09V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
    },
    palette: {
        d: "M12 3a9 9 0 0 0 0 18h1.2a2.1 2.1 0 0 0 1.5-3.6 1.9 1.9 0 0 1 1.4-3.2H17a4 4 0 0 0 4-4C21 6.3 17 3 12 3zM7.5 10.5h.01M9.5 7.5h.01M13 7h.01M16 9.5h.01",
    },
    robot: {
        d: "M7 4h10l3 5-2 10H6L4 9l3-5zM8.5 10.5h2.5l1 1.5-1 1.5H8.5L7.5 12l1-1.5zM13 12l1-1.5h2.5l1 1.5-1 1.5H14L13 12zM9 17h6M10.5 20h3M6 9h12M4 9l-2 2M20 9l2 2",
    },
    error: {
        d: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
    },
    replay: {
        d: "M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.4 2.6M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.4-2.6M21 5v4h-4M3 19v-4h4",
    },
    "git-graph": {
        d: "M5 3v18M5 7a2 2 0 0 1 2-2h10M5 12a2 2 0 0 1 2 2h10M5 17v0",
    },
    undo: {
        d: "M3 10h10a5 5 0 0 1 0 10H8M3 10l4-4M3 10l4 4",
    },
    tool: {
        d: "M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z",
    },
    terminal: {
        d: "M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM6 9l4 3-4 3M12 15h5",
    },
    write: {
        d: "M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z",
    },
    "book-open": {
        d: "M4 5.5A3.5 3.5 0 0 1 7.5 4H11v16H7.5A3.5 3.5 0 0 0 4 21.5V5.5zM20 5.5A3.5 3.5 0 0 0 16.5 4H13v16h3.5A3.5 3.5 0 0 1 20 21.5V5.5z",
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
            <path
                d={p.d as string}
                transform={p.transform as string | undefined}
            />
        </svg>
    );
}
