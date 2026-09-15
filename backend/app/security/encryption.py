"""
Reversible encryption for admin-facing password display.

Passwords are ALWAYS stored Argon2-hashed for authentication (see
password.py) - a plaintext-equivalent is never what login checks. This
module is only there so an admin can VIEW a client's existing password in
the admin UI (newer accounts created after this feature ships store an
encrypted copy next to the hash).

The tradeoff is deliberate and documented: a reversible copy is weaker
than a one-way hash, so it is:

- encrypted with Fernet using a key derived from the app secret_key
  (settings.secret_key), never stored alongside the same material,
- only ever decrypted and returned on the admin-only passwords endpoint,
- written for login password AND download password at create/change time.

Existing clients created before this feature won't have an encrypted copy;
they will report "not available" until an admin resets the password (which
then stores the copy). Nothing about auth changes - hash_password /
verify_password in password.py is untouched by this.
"""

from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import get_settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = urlsafe_b64encode(sha256(get_settings().secret_key.encode()).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_password(plain_password: str) -> str:
    """Encrypt a plaintext password for admin-viewable storage."""
    return _get_fernet().encrypt(plain_password.encode()).decode()


def decrypt_password(token: str) -> str | None:
    """Decrypt a stored encrypted password. Returns None if the token is invalid."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None