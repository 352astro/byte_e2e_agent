import { createContext, useContext } from "react";

const FocusContext = createContext<string | null>(null);

export function FocusProvider({
  focusedId,
  children,
}: {
  focusedId: string | null;
  children: React.ReactNode;
}) {
  return (
    <FocusContext.Provider value={focusedId}>
      {children}
    </FocusContext.Provider>
  );
}

/** Returns the currently focused element id, or null. */
export function useFocusedId(): string | null {
  return useContext(FocusContext);
}
