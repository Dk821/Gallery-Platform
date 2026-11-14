import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

// Dialogs can be opened on top of each other (e.g. "Edit user" over the "Users"
// dialog). Escape must only close the one on top.
const openDialogs: symbol[] = [];

interface ModalProps {
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  xwide?: boolean;
  // Dialogs that show a one-time secret must not close by a stray backdrop click.
  closeOnBackdrop?: boolean;
}

export default function Modal({ title, description, children, onClose, wide, xwide, closeOnBackdrop = true }: ModalProps) {
  // The latest onClose lives in a ref so the dialog keeps its place in the
  // stack when its parent re-renders with a new inline callback.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const me = Symbol("dialog");
    openDialogs.push(me);
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && openDialogs[openDialogs.length - 1] === me) closeRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = openDialogs.indexOf(me);
      if (i >= 0) openDialogs.splice(i, 1);
    };
  }, []);

  const overlay = (
    <div className="sa-modal-overlay" onClick={closeOnBackdrop ? onClose : undefined} role="presentation">
      <div
        className={"sa-modal-card" + (xwide ? " sa-modal-card--xwide" : wide ? " sa-modal-card--wide" : "")}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h3>{title}</h3>
        {description && <p className="sa-modal-card__desc">{description}</p>}
        {children}
      </div>
    </div>
  );

  // Rendered into the console's own root (not inside the parent dialog), so a
  // dialog opened from another dialog is never clipped or offset by it, and the
  // console's design tokens (scoped to .sa) still apply.
  const host = typeof document !== "undefined" ? document.querySelector<HTMLElement>(".sa") : null;
  return host ? createPortal(overlay, host) : overlay;
}
