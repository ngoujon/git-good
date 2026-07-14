"""App-wide configuration paths and simple JSON settings persistence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP_NAME = "GitGood"
KEYRING_SERVICE = "com.gitgood.app"


def app_support_dir() -> Path:
    path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_support_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict[str, Any]) -> None:
    settings_path().write_text(json.dumps(settings, indent=2))
