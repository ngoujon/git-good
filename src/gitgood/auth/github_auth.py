"""Personal Access Token storage in the macOS Keychain via `keyring`."""
from __future__ import annotations

import keyring
import keyring.errors

from gitgood.config import KEYRING_SERVICE

_ACCOUNT = "github-pat"


def get_token() -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, _ACCOUNT)
    except keyring.errors.KeyringError:
        # No usable backend (e.g. a packaging gap that dropped the macOS
        # backend module) must not crash the app -- treat it as "not signed in".
        return None


def set_token(token: str) -> None:
    keyring.set_password(KEYRING_SERVICE, _ACCOUNT, token)


def clear_token() -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, _ACCOUNT)
    except keyring.errors.KeyringError:
        pass
