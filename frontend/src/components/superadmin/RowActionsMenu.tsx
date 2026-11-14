import { ReactNode, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface RowAction {
  label: string;
  onSelect?: () => void;
  /** A non-clickable heading row (e.g. a user's name) that groups the items below it. */
  header?: boolean;
  danger?: boolean;
  disabled?: boolean;
  /** Small grey line under the label, e.g. why an item is disabled. */
  hint?: string;
  /** Draws a divider above this item. */
  separated?: boolean;
}

/**
 * A compact "Actions" button that opens a small menu of row actions.
 * The menu is rendered into the console root with fixed positioning, so it is
 * never clipped by a dialog or a scrolling table.
 */
export default function RowActionsMenu({
  actions,
  label = "Actions",
  onOpen,
  emptyText,
}: {
  actions: RowAction[];
  label?: string;
  /** Called each time the menu opens (e.g. to load fresh data for it). */
  onOpen?: () => void;
  /** Shown when `actions` is empty (e.g. while loading). */
  emptyText?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Position under the button, right-aligned; flip above it when there is no room below.
  function reposition() {
    if (!buttonRef.current || !menuRef.current) return;
    const b = buttonRef.current.getBoundingClientRect();
    const m = menuRef.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(window.innerWidth - m.width - 8, b.right - m.width));
    const below = b.bottom + 6;
    const top = below + m.height > window.innerHeight - 8 ? Math.max(8, b.top - m.height - 6) : below;
    setPos({ top, left });
  }

  useLayoutEffect(() => {
    if (open) reposition();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, actions.length]);

  useEffect(() => {
    if (!open) return;
    function close() {
      setOpen(false);
    }
    // The page or table scrolling (e.g. the browser bringing the button into view) just moves
    // the button, so the menu follows it. Scrolling the menu itself changes nothing.
    function onScroll(e: Event) {
      if (menuRef.current && e.target instanceof Node && menuRef.current.contains(e.target)) return;
      reposition();
    }
    function onDown(e: MouseEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || buttonRef.current?.contains(t)) return;
      close();
    }
    // Escape closes only the menu, not the dialog behind it.
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, [open]);

  const host = typeof document !== "undefined" ? document.querySelector<HTMLElement>(".sa") : null;
  const menu: ReactNode = open && (
    <div
      ref={menuRef}
      className="sa-rowmenu"
      role="menu"
      style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
    >
      {actions.length === 0 && emptyText && <p className="sa-rowmenu__empty">{emptyText}</p>}
      {actions.map((a, i) =>
        a.header ? (
          <div key={"h" + i} className={"sa-rowmenu__head" + (i > 0 ? " sa-rowmenu__head--next" : "")}>
            {a.label}
            {a.hint && <small>{a.hint}</small>}
          </div>
        ) : (
          <div key={a.label + i}>
            {a.separated && <div className="sa-rowmenu__sep" role="separator" />}
            <button
              type="button"
              role="menuitem"
              className={"sa-rowmenu__item" + (a.danger ? " sa-rowmenu__item--danger" : "")}
              disabled={a.disabled}
              onClick={() => {
                setOpen(false);
                a.onSelect?.();
              }}
            >
              {a.label}
              {a.hint && <small>{a.hint}</small>}
            </button>
          </div>
        )
      )}
    </div>
  );

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="sa-btn sa-btn--ghost sa-btn--sm"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          setPos(null);
          if (!open) onOpen?.();
          setOpen((v) => !v);
        }}
      >
        {label} <span aria-hidden="true">▾</span>
      </button>
      {menu && (host ? createPortal(menu, host) : menu)}
    </>
  );
}
