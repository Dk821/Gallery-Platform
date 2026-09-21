interface WishlistHeartProps {
  active: boolean;
  onToggle: () => void;
  // "overlay":  the round button pinned to a photo tile.
  // "lightbox": icon + label, styled like the lightbox's other top-bar buttons.
  // "row":      icon + label, styled like the View / Download buttons of a list row.
  variant?: "overlay" | "lightbox" | "row";
}

// One heart for every place a photo can be wishlisted (grid tile, list row,
// lightbox, wishlist page). Outline = not wishlisted, filled = wishlisted.
// Drawn as an SVG rather than the ♡ / ♥ text glyphs so it renders the same
// on every platform (some render ♥ as a coloured emoji).
export default function WishlistHeart({ active, onToggle, variant = "overlay" }: WishlistHeartProps) {
  const label = active ? "Remove from wishlist" : "Add to wishlist";
  const size = variant === "lightbox" ? 15 : variant === "row" ? 14 : 18;
  const className =
    variant === "lightbox"
      ? `lightbox-icon-btn wishlist-lightbox-btn${active ? " is-active" : ""}`
      : variant === "row"
        ? `wedding-media-list-btn wishlist-row-btn${active ? " is-active" : ""}`
        : `wishlist-heart${active ? " is-active" : ""}`;
  return (
    <button
      type="button"
      className={className}
      aria-pressed={active}
      aria-label={label}
      title={label}
      // The heart sits on top of clickable tiles / inside the lightbox
      // overlay: it must not also open the lightbox or close it.
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill={active ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
      </svg>
      {variant !== "overlay" && <span>{active ? "Wishlisted" : "Wishlist"}</span>}
    </button>
  );
}
