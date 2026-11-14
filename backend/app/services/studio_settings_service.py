from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.models.studio import Studio
from app.models.studio_settings import StudioSettings


def get_studio_settings(db: DbSession, studio_id: int | None = None) -> StudioSettings:
    """
    Returns the settings row for `studio_id`, creating it with defaults on
    first call. This is the ONLY place those rows are created, so every
    reader - the settings endpoints, and any service that just wants e.g.
    the configured download-link TTL - always gets a real row back.

    studio_id=None returns the legacy single-studio row (id=1) used only for
    data not yet mapped to a studio.
    """
    env_settings = get_settings()
    if studio_id is None:
        row = db.query(StudioSettings).filter(StudioSettings.id == 1).first()
        if row is None:
            # Seed the download-link TTL from the existing env-var default
            # (settings.zip_job_ttl_hours) rather than the model's hardcoded
            # default, so a fresh row never silently changes behaviour for a
            # studio that already tuned that env var.
            row = StudioSettings(id=1, download_link_ttl_hours=env_settings.zip_job_ttl_hours)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    row = db.query(StudioSettings).filter(StudioSettings.studio_id == studio_id).first()
    if row is None:
        # Same defaults the legacy single row got: profile fields start empty
        # (the studio fills them in), TTL seeded from the env var.
        row = StudioSettings(studio_id=studio_id, download_link_ttl_hours=env_settings.zip_job_ttl_hours)
        try:
            db.add(row)
            db.commit()
        except IntegrityError:  # concurrent first request created it
            db.rollback()
            row = db.query(StudioSettings).filter(StudioSettings.studio_id == studio_id).first()
        else:
            db.refresh(row)
    return row


_UNSET = object()


def update_studio_profile(
    db: DbSession,
    studio_id: int | None,
    studio_name: str | None,
    contact_email: str | None,
    contact_phone=_UNSET,
) -> StudioSettings:
    settings_row = get_studio_settings(db, studio_id)
    settings_row.studio_name = studio_name
    settings_row.contact_email = contact_email
    if studio_id is not None:
        # Keep the tenant record in step with the profile the studio edits.
        studio = db.get(Studio, studio_id)
        if studio is not None:
            if studio_name:
                studio.name = studio_name
            studio.contact_email = contact_email
            if contact_phone is not _UNSET:
                studio.contact_phone = contact_phone
    db.commit()
    db.refresh(settings_row)
    return settings_row


def update_security_policy(
    db: DbSession, studio_id: int | None, min_client_password_length: int, download_link_ttl_hours: int
) -> StudioSettings:
    settings_row = get_studio_settings(db, studio_id)
    settings_row.min_client_password_length = min_client_password_length
    settings_row.download_link_ttl_hours = download_link_ttl_hours
    db.commit()
    db.refresh(settings_row)
    return settings_row
