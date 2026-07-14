import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import keyring.errors

from gitgood.auth import github_auth


def test_get_token_returns_none_when_backend_unavailable():
    # Regression test: on a machine/build where no keyring backend loaded
    # (e.g. a packaging gap that dropped keyring.backends.macOS), get_token()
    # must return None instead of letting NoKeyringError crash the app --
    # this call happens unguarded during AppWindow startup.
    with patch("keyring.get_password", side_effect=keyring.errors.NoKeyringError("no backend")):
        assert github_auth.get_token() is None


def test_clear_token_swallows_keyring_errors():
    with patch("keyring.delete_password", side_effect=keyring.errors.NoKeyringError("no backend")):
        github_auth.clear_token()  # must not raise
