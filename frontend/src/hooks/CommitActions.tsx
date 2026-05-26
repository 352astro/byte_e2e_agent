import { createContext, useContext } from "react";

interface CommitActionsValue {
  locked: boolean;
  checkout: (sha: string) => void;
  replay: (sha: string) => void;
}

const CommitActionsCtx = createContext<CommitActionsValue>({
  locked: false,
  checkout: () => {},
  replay: () => {},
});

export function CommitActionsProvider({
  value,
  children,
}: {
  value: CommitActionsValue;
  children: React.ReactNode;
}) {
  return (
    <CommitActionsCtx.Provider value={value}>
      {children}
    </CommitActionsCtx.Provider>
  );
}

export function useCommitActions(): CommitActionsValue {
  return useContext(CommitActionsCtx);
}
