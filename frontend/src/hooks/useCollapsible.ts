import { useState, useEffect, useCallback } from "react";

/**
 * Manages collapsed/expanded state with automatic reset when
 * defaultCollapsed changes (e.g. when streaming concludes and
 * the card should auto-collapse).
 *
 * When `controlledCollapsed` is provided the hook delegates to
 * the parent — useful when a parent manages a Set of collapsed IDs.
 */
export function useCollapsible(
    defaultCollapsed: boolean,
    controlledCollapsed?: boolean,
    onToggleControlled?: (id: string) => void,
) {
    const [internalCollapsed, setInternalCollapsed] =
        useState(defaultCollapsed);
    const isControlled = controlledCollapsed !== undefined;

    useEffect(() => {
        if (!isControlled && defaultCollapsed) setInternalCollapsed(true);
    }, [defaultCollapsed, isControlled]);

    const collapsed = isControlled ? controlledCollapsed! : internalCollapsed;

    const toggle = useCallback(
        (id: string) => {
            if (isControlled) {
                onToggleControlled?.(id);
            } else {
                setInternalCollapsed((prev) => !prev);
            }
        },
        [isControlled, onToggleControlled],
    );

    return [collapsed, toggle] as const;
}
