"""
Regenerates GOOGLE_DRIVE_REFRESH_TOKEN when it has expired or been revoked
(google.auth.exceptions.RefreshError / "invalid_grant: Token has been
expired or revoked.").

This almost always means one of:
  1. The Google Cloud OAuth consent screen is still in "Testing" publishing
     status - Google auto-expires refresh tokens for testing-mode apps
     after 7 days of issuance, no matter how active the app is. This is
     the most common cause if the error recurs every ~week.
  2. Someone revoked the app's access under the Drive account's
     https://myaccount.google.com/permissions.
  3. The refresh token simply wasn't used for 6+ months.

Run this on a machine with a real web browser (it opens one and spins up a
brief local server to catch the OAuth redirect - it will NOT work inside a
headless/remote shell with no browser). It reads GOOGLE_DRIVE_CLIENT_ID and
GOOGLE_DRIVE_CLIENT_SECRET from backend/.env, walks you through the Google
consent screen, then prints (and optionally writes back into .env) a fresh
GOOGLE_DRIVE_REFRESH_TOKEN.

Usage:
    cd backend
    python scripts/generate_drive_refresh_token.py

IMPORTANT: authorize with the SAME Google account that owns/has access to
the Drive folder in GOOGLE_DRIVE_ROOT_FOLDER_ID - authorizing with the
wrong account will "succeed" but the app won't be able to see that folder.
"""

import os
import platform
import re
import shutil
import sys
from pathlib import Path


def _find_chrome() -> str | None:
    """Best-effort search for a real Chrome executable on this machine."""
    system = platform.system()
    candidates: list[str] = []
    if system == "Windows":
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var)
            if base:
                candidates.append(str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    elif system == "Darwin":
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

    for path in candidates:
        if Path(path).is_file():
            return path

    # Linux, or Chrome not found at the usual install path above - fall
    # back to whatever's on PATH under a name Chrome commonly ships as.
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


# Must happen BEFORE google_auth_oauthlib (which imports the stdlib
# `webbrowser` module) is imported below - `webbrowser` only reads the
# BROWSER env var once, at its own import time, to decide which browser
# `webbrowser.open()` prefers over the OS default. Setting it any later
# has no effect.
_chrome_path = _find_chrome()
if _chrome_path:
    quoted = f'"{_chrome_path}"' if " " in _chrome_path else _chrome_path
    os.environ["BROWSER"] = f"{quoted} %s"
else:
    print(
        "Could not find a Chrome install in the usual locations - falling back to "
        "your OS default browser instead.\n"
    )

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402 - see BROWSER note above

SCOPES = ["https://www.googleapis.com/auth/drive"]
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _read_env_value(env_text: str, key: str) -> str:
    match = re.search(rf"^{key}=(.*)$", env_text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def main() -> None:
    if not ENV_PATH.exists():
        print(f"Could not find {ENV_PATH} - run this from the backend/ directory.")
        sys.exit(1)

    env_text = ENV_PATH.read_text(encoding="utf-8")
    client_id = _read_env_value(env_text, "GOOGLE_DRIVE_CLIENT_ID")
    client_secret = _read_env_value(env_text, "GOOGLE_DRIVE_CLIENT_SECRET")
    redirect_uri = _read_env_value(env_text, "GOOGLE_DRIVE_REDIRECT_URI")

    if not client_id or not client_secret:
        print("GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET are missing from .env.")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }

    browser_note = f"Chrome ({_chrome_path})" if _chrome_path else "your default browser"
    print(f"Opening {browser_note} to sign in to Google Drive...")
    print("Sign in with the SAME account that owns the target Drive folder.\n")

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # port=0 -> OS picks a free local port. Works out of the box for
    # "Desktop app" OAuth clients. If this client was created as a "Web
    # application" type instead, Google will reject the redirect with
    # redirect_uri_mismatch - see the fallback instructions this script
    # prints in that case.
    try:
        credentials = flow.run_local_server(port=0)
    except Exception as exc:  # noqa: BLE001
        print(f"\nLocal-server auth flow failed: {exc}")
        print(
            "\nIf this says redirect_uri_mismatch, this OAuth client was created as a "
            "'Web application' type, not 'Desktop app'. Easiest fix: in Google Cloud "
            "Console -> APIs & Services -> Credentials, create a new OAuth client with "
            "type 'Desktop app', put ITS client_id/client_secret into backend/.env, and "
            "re-run this script."
        )
        sys.exit(1)

    new_token = credentials.refresh_token
    if not new_token:
        print(
            "\nGoogle didn't return a refresh_token. This happens when the same account "
            "already has an active grant for this app - go to "
            "https://myaccount.google.com/permissions, remove this app's access, then "
            "re-run this script so Google is forced to issue a fresh one."
        )
        sys.exit(1)

    print(f"\nNew refresh token:\n{new_token}\n")

    answer = input("Write this into backend/.env now, replacing the old value? [y/N] ").strip().lower()
    if answer == "y":
        updated = re.sub(
            r"^GOOGLE_DRIVE_REFRESH_TOKEN=.*$",
            f"GOOGLE_DRIVE_REFRESH_TOKEN={new_token}",
            env_text,
            count=1,
            flags=re.MULTILINE,
        )
        ENV_PATH.write_text(updated, encoding="utf-8")
        print(f"Updated {ENV_PATH}. Restart the backend process for it to take effect.")
    else:
        print("Not written. Paste the value above into GOOGLE_DRIVE_REFRESH_TOKEN in backend/.env yourself.")


if __name__ == "__main__":
    main()
