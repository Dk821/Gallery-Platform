"""Shared SQL aggregate expressions for Media counts and byte totals.

One place to build the "count of photos / count of videos / total bytes"
expressions, so every caller emits SQL the production database can
actually run.

The obvious spelling - ``func.count(Media.id).filter(Media.file_type ==
"photo")`` - compiles to ``count(...) FILTER (WHERE ...)``, which only
Postgres and SQLite understand. MySQL 8 has no FILTER clause, so on the
real database that query dies with a 1064 syntax error (it passes the
test suite, which runs on SQLite, which is exactly why it is worth
pinning down here). ``SUM(CASE WHEN ... THEN 1 ELSE 0 END)`` is the
portable equivalent and gives the same number, so these helpers use that
instead.

Both are wrapped in COALESCE so an album (or client) with no media at
all reports 0 rather than NULL - the API contract is a number, and the
album list also uses the same expressions for its outer COALESCE.
"""

from sqlalchemy import case, func

from app.models.media import Media

PHOTO = "photo"
VIDEO = "video"


def photo_count_column():
    """Count of the client's/album's photo rows in the current GROUP BY."""
    return func.coalesce(func.sum(case((Media.file_type == PHOTO, 1), else_=0)), 0)


def video_count_column():
    """Count of the client's/album's video rows in the current GROUP BY."""
    return func.coalesce(func.sum(case((Media.file_type == VIDEO, 1), else_=0)), 0)


def total_bytes_column():
    """Sum of Media.file_size in the current GROUP BY (0 when there are none)."""
    return func.coalesce(func.sum(Media.file_size), 0)
