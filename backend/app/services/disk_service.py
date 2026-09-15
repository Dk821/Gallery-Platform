"""
Disk-space protection for the VPS-in-the-upload-path architecture
(Section 5). A single upload's size alone isn't enough to decide "is there
room?" - several uploads can be received concurrently, so this tracks
in-flight reservations across all of them and only accepts a new one if
free disk minus every other active reservation minus a safety reserve
still covers it.

Known limitation: in-process only, same caveat as upload_concurrency.py -
multiple worker processes would each reserve independently against the
same physical disk. Fine for the single-process VPS deployment this
project targets; would need an external store to generalize.
"""

import shutil
import threading


class InsufficientDiskSpaceError(Exception):
    def __init__(self, required_bytes: int, available_bytes: int):
        self.required_bytes = required_bytes
        self.available_bytes = max(available_bytes, 0)
        super().__init__(
            f"Insufficient disk space: need {required_bytes} bytes, "
            f"only {self.available_bytes} bytes available after reservations and safety margin."
        )


class DiskReservationTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._reservations: dict[str, int] = {}

    def total_reserved(self, *, exclude_key: str | None = None) -> int:
        with self._lock:
            return sum(v for k, v in self._reservations.items() if k != exclude_key)

    def try_reserve(self, key: str, size_bytes: int, *, min_free_bytes: int, path: str = "/") -> None:
        """
        Atomically checks free disk space (minus every OTHER active
        reservation and the configured safety margin) and, if there's
        room, records this reservation. Raises InsufficientDiskSpaceError
        and reserves nothing otherwise.
        """
        with self._lock:
            free = shutil.disk_usage(path).free
            already_reserved = sum(v for k, v in self._reservations.items() if k != key)
            available = free - already_reserved - min_free_bytes
            if size_bytes > available:
                raise InsufficientDiskSpaceError(size_bytes, available)
            self._reservations[key] = size_bytes

    def release(self, key: str) -> None:
        with self._lock:
            self._reservations.pop(key, None)

    def get_headroom(self, *, path: str = "/", min_free_bytes: int = 0) -> dict:
        """
        Snapshot of the actual VPS disk backing uploads/ZIP jobs - distinct
        from Google Drive's quota (which lives entirely with the storage
        provider and says nothing about the local disk this server writes
        spooled uploads and in-progress ZIPs to). Used by the admin storage
        page so "is the server itself about to run out of disk" is visible
        without SSHing in and running `df`.
        """
        with self._lock:
            usage = shutil.disk_usage(path)
            reserved = sum(self._reservations.values())

        # What try_reserve() would actually treat as "room for a new
        # upload right now" - free space minus every in-flight
        # reservation minus the configured safety margin, floored at 0
        # rather than shown negative (which would be technically accurate
        # but confusing on a dashboard).
        effective_available = max(usage.free - reserved - min_free_bytes, 0)

        return {
            "path": path,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "reserved_bytes": reserved,
            "min_free_bytes": min_free_bytes,
            "effective_available_bytes": effective_available,
            "percent_used": round((usage.used / usage.total) * 100, 1) if usage.total else 0.0,
        }


_tracker = DiskReservationTracker()


def get_disk_tracker() -> DiskReservationTracker:
    return _tracker
