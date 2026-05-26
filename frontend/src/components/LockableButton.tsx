/**
 * Auto-disables when `locked` is true.
 * Use for any action that mutates project state.
 */
export default function LockableButton({
  icon,
  label,
  confirming,
  locked,
  onToggle,
  onConfirm,
}: {
  icon: React.ReactNode;
  label: string;
  confirming: boolean;
  locked: boolean;
  onToggle: () => void;
  onConfirm: () => void;
}) {
  const disabled = locked;
  return (
    <span
      className={
        "lockable-btn" +
        (confirming ? " lockable-btn--confirm" : "") +
        (disabled ? " lockable-btn--locked" : "")
      }
      onClick={(e) => {
        e.stopPropagation();
        if (disabled) return;
        if (confirming) onConfirm();
        else onToggle();
      }}
    >
      {icon}
      {confirming ? "confirm" : label}
    </span>
  );
}
