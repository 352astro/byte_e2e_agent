import { createContext, useContext } from "react";

interface FocusContextType {
  focusedId: string | null;
  focusElement: (id: string) => void;
}

export const FocusContext = createContext<FocusContextType>({
  focusedId: null,
  focusElement: () => {},
});

export function useFocus() {
  return useContext(FocusContext);
}

/** Helper: wrap content in a focusable span if id is provided. */
export function Focusable({
  id,
  children,
  className = "",
}: {
  id: string;
  children: React.ReactNode;
  className?: string;
}) {
  const { focusedId, focusElement } = useFocus();
  const isFocused = focusedId === id;

  return (
    <span
      className={`${className}${isFocused ? " card-latest" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        focusElement(id);
      }}
    >
      {children}
    </span>
  );
}
