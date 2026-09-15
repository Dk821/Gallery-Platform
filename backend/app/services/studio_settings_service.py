from sqlalchemy.orm import Session as DbSession

from app.config.settings import get_settings
from app.models.studio_settings import StudioSettings


def get_studio_settings(db: DbSession) -> StudioSettings:
    """
    Returns the single studio_settings row, creating it with the model's
    defaults on first call. This is the ONLY place that row is created, so
    every reader - this feature's own endpoints, and any other service
    that just wants e.g. the configured download-link TTL - always gets a
    real row back and never has to special-case "not configured yet".
    """
    settings_row = db.query(StudioSettings).filter(StudioSettings.id == 1).first()
    if settings_row is None:
        # Seed the download-link TTL from the existing env-var default
        # (settings.zip_job_ttl_hours) rather than the model's own
        # hardcoded default, so a fresh row never silently changes
        # behavior for a studio that already tuned that env var.
        env_settings = get_settings()
        settings_row = StudioSettings(id=1, download_link_ttl_hours=env_settings.zip_job_ttl_hours)
        db.add(settings_row)
        db.commit()
        db.refresh(settings_row)
    return settings_row


def update_studio_profile(db: DbSession, studio_name: str | None, contact_email: str | None) -> StudioSettings:
    settings_row = get_studio_settings(db)
    settings_row.studio_name = studio_name
    settings_row.contact_email = contact_email
    db.commit()
    db.refresh(settings_row)
    return settings_row


def update_security_policy(
    db: DbSession, min_client_password_length: int, download_link_ttl_hours: int
) -> StudioSettings:
    settings_row = get_studio_settings(db)
    settings_row.min_client_password_length = min_client_password_length
    settings_row.download_link_ttl_hours = download_link_ttl_hours
    db.commit()
    db.refresh(settings_row)
    return settings_row
