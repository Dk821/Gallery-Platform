interface PaginationProps {
  page: number;
  limit: number;
  total: number;
  onPage: (page: number) => void;
}

export default function Pagination({ page, limit, total, onPage }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (total <= limit) return null;
  const from = (page - 1) * limit + 1;
  const to = Math.min(page * limit, total);
  return (
    <div className="sa-pagination">
      <span className="sa-pagination__info">
        {from}–{to} of {total}
      </span>
      <div className="sa-pagination__buttons">
        <button className="sa-btn sa-btn--ghost sa-btn--sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          Previous
        </button>
        <span className="sa-pagination__page">
          Page {page} / {pages}
        </span>
        <button className="sa-btn sa-btn--ghost sa-btn--sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}
