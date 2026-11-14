import { createContext, ReactNode, useCallback, useContext, useRef, useState } from "react";

type ToastKind = "success" | "error";
interface ToastItem {
  id: number;
  kind: ToastKind;
  text: string;
}

const ToastContext = createContext<(kind: ToastKind, text: string) => void>(() => {});

export function useToast() {
  const push = useContext(ToastContext);
  return {
    success: (text: string) => push("success", text),
    error: (text: string) => push("error", text),
  };
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = nextId.current++;
    setItems((prev) => [...prev, { id, kind, text }]);
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="sa-toast-stack" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`sa-toast sa-toast--${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
