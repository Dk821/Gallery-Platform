import { ReactNode, useEffect } from "react";

interface ModalProps {
  title: string;
  description?: string;
  children: ReactNode;
  onClose: () => void;
  // Extra class on .modal-card, for the few dialogs that need more width
  // than the default form-sized card.
  className?: string;
}

export default function Modal({ title, description, children, onClose, className }: ModalProps) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className={`modal-card${className ? ` ${className}` : ""}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h3>{title}</h3>
        {description && <p>{description}</p>}
        {children}
      </div>
    </div>
  );
}
