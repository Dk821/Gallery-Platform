import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

// Mirrors MAX_COMMENT_LENGTH in backend/app/schemas/comment.py. The textarea
// enforces it, but the server is the real gate.
const MAX_LENGTH = 2000;

interface BookCommentPanelProps {
  pageNumber: number;
  totalPages: number;
  initialValue: string;
  hasExisting: boolean;
  saving: boolean;
  error: string | null;
  onSubmit: (comment: string) => void;
  onDelete: () => void;
  onClose: () => void;
}

/**
 * The client's note sheet for the page currently on show. A page has at most
 * one note (the backend upserts on client + album + page), so this is always
 * "write" or "edit", never a list.
 */
export default function BookCommentPanel({
  pageNumber,
  totalPages,
  initialValue,
  hasExisting,
  saving,
  error,
  onSubmit,
  onDelete,
  onClose,
}: BookCommentPanelProps) {
  const [draft, setDraft] = useState(initialValue);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Follow the page if it changes underneath the sheet (e.g. a scrub or an
  // autoplay turn landed just before it opened).
  useEffect(() => {
    setDraft(initialValue);
  }, [initialValue, pageNumber]);

  useEffect(() => {
    const input = textareaRef.current;
    if (!input) return;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }, []);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const trimmed = draft.trim();
  const unchanged = hasExisting && trimmed === initialValue.trim();
  const canSubmit = !saving && trimmed.length > 0;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (canSubmit) onSubmit(trimmed);
  }

  function handleKeyDown(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (canSubmit) onSubmit(trimmed);
    }
  }

  function handleDelete() {
    if (saving || !hasExisting) return;
    if (window.confirm("Remove your note from this page?")) onDelete();
  }

  return (
    <div className="book-comment" role="presentation" onClick={onClose}>
      <form
        className="book-comment__card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="book-comment-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <div className="book-comment__head">
          <div>
            <p className="book-comment__eyebrow">Your note</p>
            <h2 className="book-comment__title" id="book-comment-title">
              Page {pageNumber} <span>of {totalPages}</span>
            </h2>
          </div>
          <button
            type="button"
            className="book-comment__close"
            onClick={onClose}
            disabled={saving}
            aria-label="Close note"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <textarea
          ref={textareaRef}
          className="book-comment__input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Tell the studio what you would like changed, removed or retouched on this page…"
          maxLength={MAX_LENGTH}
          rows={5}
          disabled={saving}
        />

        <div className="book-comment__meta">
          <span>Only you and the studio can see this.</span>
          <span className={draft.length >= MAX_LENGTH ? "is-full" : undefined}>
            {draft.length}/{MAX_LENGTH}
          </span>
        </div>

        {error && (
          <p className="book-comment__error" role="alert">
            {error}
          </p>
        )}

        <div className="book-comment__actions">
          {hasExisting ? (
            <button type="button" className="book-comment__delete" onClick={handleDelete} disabled={saving}>
              Remove note
            </button>
          ) : (
            <span />
          )}

          <div className="book-comment__actions-end">
            <button type="button" className="book-comment__cancel" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="book-comment__submit" disabled={!canSubmit}>
              {saving ? "Saving…" : unchanged ? "Next page" : "Save & next page"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
