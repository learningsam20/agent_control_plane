from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now stored as naive (SQLite-friendly), avoiding the
    deprecated ``datetime.utcnow()``."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
